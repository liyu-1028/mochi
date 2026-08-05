"""FastAPI 入口：/health + /ws（协议 v0.1 事件流）+ /config（REST 管理端点）。

启动流程（Zero Config，config-format.md §6）：
1. lifespan 探测本地 Ollama（1.5s 硬超时）
2. load_config：首启生成默认配置（探测到 Ollama → 预填默认 provider；否则试用模式）
3. ProviderRegistry 就绪，/ws 与 /config 端点可用
4. 写 <userData>/runtime.json（端口/pid/协议版本）供桌面壳发现（M1-S0）
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__
from .agent import RunManager
from .agent.ollama_probe import probe_ollama
from .agent.registry import ProviderRegistry
from .agent.service import AgentService
from .api import config_router, session_router
from .api.security import ALLOWED_CORS_ORIGINS, SensitiveDataFilter
from .config import AppConfig, load_config
from .events import (
    EVENT_TYPES,
    PROTOCOL_VERSION,
    SERVER_NAME,
    ChatCancelData,
    ChatInterruptData,
    ChatSendData,
    ErrorCode,
    ErrorPayload,
    HelloAckData,
    HelloData,
    HelloErrorData,
    PongData,
    ServerInfo,
    StateChangeData,
    make_frame,
)
from .paths import get_config_path
from .runtime import remove_runtime_file, resolve_port, write_runtime_file
from .secrets import KeyStore
from .store import SessionStore

logger = logging.getLogger(__name__)

# 休眠状态（功能清单 2.2）：5 分钟无业务帧触发。
# 业务帧 = 握手与对话命令；ping 心跳不计——否则 30s 心跳永远重置计时，
# 休眠永不触发（详见 ADR-0002 D9）。
_SLEEP_THRESHOLD_S = 300.0
_BUSINESS_FRAME_TYPES = frozenset({"hello", "chat.send", "chat.cancel", "chat.interrupt"})


def _install_log_filter() -> None:
    """把脱敏过滤器挂到 root logger 与其 handler（幂等）。

    uvicorn 默认日志配置只给 uvicorn.* logger 装 handler，root 无 handler 时
    mochi_server.* 的日志会被静默丢弃——补一个带时间戳的 stderr handler
    （仅当 root 无任何 handler；uvicorn 自有 logger 均 propagate=False，不重复）。
    """
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
        )
        root.addHandler(handler)
    targets: list[logging.Logger | logging.Handler] = [root, *root.handlers]
    for target in targets:
        if not any(isinstance(f, SensitiveDataFilter) for f in target.filters):
            target.addFilter(SensitiveDataFilter())


def _now_ms() -> int:
    return int(time.time() * 1000)


def _setup_file_logging() -> None:
    """把日志落盘到 <userData>/mochi-server.log（幂等）。

    release 下 sidecar 的 stdout/stderr 被桌面壳丢弃（sidecar.rs Stdio::null），
    不落盘则任何运行期问题（含 CORS 预检/请求到达情况）都无从排查（功能清单 1.8 铺垫）。
    """
    from .paths import get_data_dir

    root = logging.getLogger()
    if any(isinstance(h, logging.FileHandler) for h in root.handlers):
        return  # 已装过（多次 create_app / 测试复用）
    try:
        log_path = get_data_dir() / "mochi-server.log"
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler.addFilter(SensitiveDataFilter())
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    except OSError:
        # 落盘失败不阻断启动（控制台/丢弃日志仍可工作）
        pass


class RequestLogMiddleware(BaseHTTPMiddleware):
    """记录每个 HTTP 请求的 method/path/Origin，用于排查 CORS 与连通问题。"""

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin", "-")
        client = request.client.host if request.client else "-"
        logger.info(
            "HTTP %s %s origin=%s client=%s", request.method, request.url.path, origin, client
        )
        return await call_next(request)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    _install_log_filter()  # uvicorn 在启动期才装 handler，这里再补一次
    _setup_file_logging()  # 日志落盘，release 下可查请求/CORS 到达情况
    if app.state.registry is None and app.state.agent is None:
        probe = await probe_ollama()
        config = load_config(
            get_config_path(),
            ollama_available=probe.available,
            ollama_model=probe.models[0] if probe.models else None,
        )
        app.state.registry = ProviderRegistry(config, KeyStore(), store=app.state.store)
        logger.info(
            "配置就绪：default_provider=%s（Ollama %s）",
            config.model.default_provider,
            "已发现" if probe.available else "未发现",
        )
    # 端口发现（M1-S0）：uvicorn 的端口经 MOCHI_SIDECAR_PORT 约定，就绪即写。
    # 注：lifespan 先于 socket 监听执行，前端连接由重连机制兜住毫秒级窗口。
    write_runtime_file(resolve_port())
    yield
    remove_runtime_file()
    # 关闭会话库连接（测试用 TestClient 同样走此路径）
    store = getattr(app.state, "store", None)
    if store is not None:
        await store.close()


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
    # 后加 → 最外层：先于 CORS 记录每个请求（含预检 OPTIONS）的 Origin
    app.add_middleware(RequestLogMiddleware)
    app.state.agent = agent
    # 会话持久化（M1-S1）：全局共享一个 SessionStore，Agent 与 REST 路由同源
    app.state.store = SessionStore()
    app.state.registry = (
        ProviderRegistry(config, key_store, store=app.state.store) if config is not None else None
    )
    app.state.config_path = get_config_path()
    app.include_router(config_router)
    app.include_router(session_router)
    _install_log_filter()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "protocol": PROTOCOL_VERSION}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        logger.info("WS 客户端已连接")
        # 显式 agent 优先；否则按回合从 registry 解析（支持热切换）
        if app.state.agent is not None:
            agent_source = app.state.agent
        elif app.state.registry is not None:
            agent_source = app.state.registry.current_agent
        else:
            raise RuntimeError("应用未初始化：lifespan 未执行（TestClient 请用 with 语法）")
        # 两个时限可经 app.state 注入（测试加速用）：error 表情停留 / 休眠阈值
        manager = RunManager(
            agent_source,
            ws.send_json,
            error_recovery_delay_s=getattr(app.state, "error_recovery_delay_s", 3.0),
        )
        sleep_threshold_s = getattr(app.state, "sleep_threshold_s", _SLEEP_THRESHOLD_S)
        check_interval_s = min(30.0, sleep_threshold_s)
        handshaken = False
        sleeping = False
        last_activity = time.monotonic()  # 只由业务帧刷新；ping 心跳不计
        try:
            while True:
                try:
                    frame = await asyncio.wait_for(ws.receive_json(), timeout=check_interval_s)
                except TimeoutError:
                    frame = None  # 周期性醒来检查休眠条件

                if frame is not None:
                    msg_type = frame.get("type")
                    if msg_type in _BUSINESS_FRAME_TYPES:
                        last_activity = time.monotonic()
                        if sleeping:  # 唤醒：先回 idle 再处理命令（协议状态严格对应）
                            await ws.send_json(
                                make_frame(
                                    EVENT_TYPES["state.change"],
                                    StateChangeData(state="idle"),
                                    _now_ms(),
                                )
                            )
                            sleeping = False
                else:
                    msg_type = None

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
                        elif msg_type == "chat.cancel":
                            payload = ChatCancelData.model_validate(frame["data"])
                            await manager.cancel_run(payload.run_id)
                        else:  # chat.interrupt：打断播报（协议 §4，reason="interrupted"）
                            payload = ChatInterruptData.model_validate(frame["data"])
                            await manager.interrupt_run(payload.run_id)
                    except ValidationError:
                        logger.warning("命令负载校验失败：%s %s", msg_type, frame.get("data"))
                    except KeyError:
                        logger.warning("命令缺少 data：%s", msg_type)

                # 休眠检查（2.2）：已握手、无活跃回合、长时间无业务帧。
                # ping 心跳不刷新 last_activity，否则 30s 心跳令休眠永不触发。
                if (
                    handshaken
                    and not sleeping
                    and not manager.has_active_runs
                    and time.monotonic() - last_activity >= sleep_threshold_s
                ):
                    await ws.send_json(
                        make_frame(
                            EVENT_TYPES["state.change"],
                            StateChangeData(state="sleeping"),
                            _now_ms(),
                        )
                    )
                    sleeping = True

        except WebSocketDisconnect:
            return

    return app


app = create_app()
