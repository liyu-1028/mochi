"""FastAPI 入口：/health + /ws（协议 v0.1 事件流）+ /config（REST 管理端点）。

启动流程（Zero Config，config-format.md §6）：
1. lifespan 探测本地 Ollama（1.5s 硬超时）
2. load_config：首启生成默认配置（探测到 Ollama → 预填默认 provider；否则试用模式）
3. ProviderRegistry 就绪，/ws 与 /config 端点可用

TODO(M1)：sidecar 端口发现机制（写 <userData>/runtime.json 供桌面壳读取）。
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from . import __version__
from .agent import RunManager
from .agent.ollama_probe import probe_ollama
from .agent.registry import ProviderRegistry
from .agent.service import AgentService
from .api import config_router
from .api.security import ALLOWED_CORS_ORIGINS, SensitiveDataFilter
from .config import AppConfig, load_config
from .events import (
    EVENT_TYPES,
    PROTOCOL_VERSION,
    SERVER_NAME,
    ChatCancelData,
    ChatSendData,
    ErrorCode,
    ErrorPayload,
    HelloAckData,
    HelloData,
    HelloErrorData,
    PongData,
    ServerInfo,
    make_frame,
)
from .paths import get_config_path
from .secrets import KeyStore

logger = logging.getLogger(__name__)


def _install_log_filter() -> None:
    """把脱敏过滤器挂到 root logger 与其 handler（幂等）。"""
    root = logging.getLogger()
    targets: list[logging.Logger | logging.Handler] = [root, *root.handlers]
    for target in targets:
        if not any(isinstance(f, SensitiveDataFilter) for f in target.filters):
            target.addFilter(SensitiveDataFilter())


def _now_ms() -> int:
    return int(time.time() * 1000)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    _install_log_filter()  # uvicorn 在启动期才装 handler，这里再补一次
    if app.state.registry is None and app.state.agent is None:
        probe = await probe_ollama()
        config = load_config(
            get_config_path(),
            ollama_available=probe.available,
            ollama_model=probe.models[0] if probe.models else None,
        )
        app.state.registry = ProviderRegistry(config, KeyStore())
        logger.info(
            "配置就绪：default_provider=%s（Ollama %s）",
            config.model.default_provider,
            "已发现" if probe.available else "未发现",
        )
    yield


def create_app(
    agent: AgentService | None = None,
    *,
    config: AppConfig | None = None,
    key_store: KeyStore | None = None,
) -> FastAPI:
    """应用工厂。

    - ``agent`` 显式注入（S1 兼容路径）：跳过配置/registry，直接使用该 agent；
    - ``config`` 显式注入：跳过 lifespan 的探测与文件读写，直接构建 registry；
    - 都不传（生产路径）：lifespan 内探测 Ollama + 加载/生成配置。
    """
    app = FastAPI(title="mochi-server", version=__version__, lifespan=_lifespan)
    # CORS：前端（1420 / Tauri 壳）与 sidecar（8199）不同源，浏览器对非简单请求
    # 先发 OPTIONS 预检；不挂中间件时路由层回 405（测试报告 2026-08-03）。
    # 源白名单见 security.ALLOWED_CORS_ORIGINS——不接受通配。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(ALLOWED_CORS_ORIGINS),
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.state.agent = agent
    app.state.registry = ProviderRegistry(config, key_store) if config is not None else None
    app.state.config_path = get_config_path()
    app.include_router(config_router)
    _install_log_filter()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "protocol": PROTOCOL_VERSION}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        # 显式 agent 优先；否则按回合从 registry 解析（支持热切换）
        if app.state.agent is not None:
            agent_source = app.state.agent
        elif app.state.registry is not None:
            agent_source = app.state.registry.current_agent
        else:
            raise RuntimeError("应用未初始化：lifespan 未执行（TestClient 请用 with 语法）")
        manager = RunManager(agent_source, ws.send_json)
        handshaken = False
        try:
            while True:
                frame = await ws.receive_json()
                msg_type = frame.get("type")

                if msg_type == "hello":
                    hello = HelloData.model_validate(frame.get("data", {}))
                    if PROTOCOL_VERSION in hello.versions:
                        ack = HelloAckData(
                            version=PROTOCOL_VERSION,
                            server=ServerInfo(name=SERVER_NAME, version=__version__),
                        )
                        await ws.send_json(make_frame(EVENT_TYPES["hello_ack"], ack, _now_ms()))
                        handshaken = True
                    else:
                        err = HelloErrorData(
                            error=ErrorPayload(
                                code=ErrorCode.VERSION_MISMATCH,
                                message=f"协议版本不兼容：客户端 {hello.versions}，"
                                f"服务端支持 {PROTOCOL_VERSION}",
                                retryable=False,
                                hint="请更新 Mochi 到最新版本",
                            )
                        )
                        await ws.send_json(make_frame(EVENT_TYPES["hello_error"], err, _now_ms()))
                        await ws.close()
                        return

                elif msg_type == "ping":
                    token = frame.get("data", {}).get("token")
                    await ws.send_json(
                        make_frame(EVENT_TYPES["pong"], PongData(token=token), _now_ms())
                    )

                elif msg_type in ("chat.send", "chat.cancel", "chat.interrupt"):
                    if not handshaken:
                        continue  # 握手前拒绝业务命令（协议 §2）
                    try:
                        if msg_type == "chat.send":
                            await manager.start_run(ChatSendData.model_validate(frame["data"]))
                        else:
                            # TODO(M1)：interrupt 与 cancel 语义分离（停止播报 vs 丢弃生成）
                            payload = ChatCancelData.model_validate(frame["data"])
                            await manager.cancel_run(payload.run_id)
                    except ValidationError:
                        logger.warning("命令负载校验失败：%s %s", msg_type, frame.get("data"))
                    except KeyError:
                        logger.warning("命令缺少 data：%s", msg_type)

        except WebSocketDisconnect:
            return

    return app


app = create_app()
