"""FastAPI 入口：/health + /ws（协议 v0.1 事件流）+ /config（REST 管理端点）。

启动流程（Zero Config，config-format.md §6）：
1. lifespan 探测本地 Ollama（1.5s 硬超时）
2. load_config：首启生成默认配置（探测到 Ollama → 预填默认 provider；否则试用模式）
3. AgentFactory 就绪，/ws 与 /config 端点可用
4. 写 <userData>/runtime.json（端口/pid/协议版本）供桌面壳发现（M1-S0）
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__
from .agent import RunManager
from .agent.llm_agent import LLMAgentService
from .agent.ollama_probe import probe_ollama
from .agent.registry import AgentFactory
from .agent.service import AgentService
from .api import config_router, memory_router, session_router, skin_router, tts_router
from .api.security import ALLOWED_CORS_ORIGINS, SensitiveDataFilter, localhost_only
from .attention.bridge import CompanionCoordinator, start_pump_loop
from .attention.engine import AttentionEngine, settings_from_config
from .config import AppConfig, load_config
from .events import (
    EVENT_TYPES,
    LOCOMOTION_ACTIONS,
    PROTOCOL_VERSION,
    SEMANTIC_ACTIONS,
    SERVER_NAME,
    CharacterCueData,
    ChatCancelData,
    ChatInterruptData,
    ChatSendData,
    CompanionSignalData,
    CueBodyChannel,
    CueChannels,
    CueFaceChannel,
    CueLocomotionChannel,
    Emotion,
    ErrorCode,
    ErrorPayload,
    HelloAckData,
    HelloData,
    HelloErrorData,
    PongData,
    ServerInfo,
    StateChangeData,
    ToolConfirmData,
    make_frame,
)
from .langgraph_checkpoints import build_checkpointer
from .paths import get_config_path
from .runtime import remove_runtime_file, resolve_port, write_runtime_file
from .secrets import KeyStore
from .skin.registry import SkinRegistry
from .store import SessionStore

logger = logging.getLogger(__name__)

# 休眠状态（功能清单 2.2）：5 分钟无业务帧触发。
# 业务帧 = 握手与对话命令；ping 心跳不计——否则 30s 心跳永远重置计时，
# 休眠永不触发（详见 ADR-0002 D9）。
_SLEEP_THRESHOLD_S = 300.0
_BUSINESS_FRAME_TYPES = frozenset(
    {"hello", "chat.send", "chat.cancel", "chat.interrupt", "tool.confirm", "companion.signal"}
)

# 调试辅助（M-D 验证用）：活跃 ws 发送通道注册表——POST /dev/cue 广播 character.cue。
# 不属于协议面，路由挂 localhost_only 仅本机可达；GUI 实测/手工验证驱动角色表演用。
_DEV_WS_SENDERS: list[Any] = []


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


def _resolve_app_config(app: FastAPI) -> AppConfig | None:
    """取当前生效配置：显式注入优先，其次 registry 持有（热切换后仍最新）。"""
    if app.state.agent is not None:  # 测试显式注入路径：无 config 语境
        return None
    registry = getattr(app.state, "registry", None)
    if registry is not None and getattr(registry, "_config", None) is not None:
        cfg = registry._config  # type: ignore[attr-defined]
        if isinstance(cfg, AppConfig):
            return cfg
    return None


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
        # checkpoint（ADR-0008 D4）：独立连接独立文件，装配见 langgraph_checkpoints
        ckpt_conn, saver = await build_checkpointer()
        app.state.checkpoint_conn = ckpt_conn
        app.state.registry = AgentFactory(
            config,
            KeyStore(),
            store=app.state.store,
            checkpointer=saver,
            config_path=get_config_path(),  # 工具白名单落盘目标（6.5）
        )
        logger.info(
            "配置就绪：default_profile=%s（Ollama %s）",
            config.model.default_profile,
            "已发现" if probe.available else "未发现",
        )
    # 端口发现（M1-S0）：uvicorn 的端口经 MOCHI_SIDECAR_PORT 约定，就绪即写。
    # 注：lifespan 先于 socket 监听执行，前端连接由重连机制兜住毫秒级窗口。
    write_runtime_file(resolve_port())
    yield
    remove_runtime_file()
    # 关闭 checkpoint 连接（M1-S4，ADR-0008 D4）
    ckpt_conn = getattr(app.state, "checkpoint_conn", None)
    if ckpt_conn is not None:
        await ckpt_conn.close()
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
    app.state.config_path = get_config_path()
    # 皮肤注册表（M1-S1）：用户皮肤资源经 /user-skins 路由分发，base URL 带端口；
    # 同时作为 AgentFactory 的能力注入来源（G2 提示词按皮肤可演动作收窄）
    app.state.skin_registry = SkinRegistry(http_base_url=f"http://127.0.0.1:{resolve_port()}")
    app.state.registry = (
        AgentFactory(
            config,
            key_store,
            store=app.state.store,
            config_path=app.state.config_path,
            skin_registry=app.state.skin_registry,
        )
        if config is not None
        else None
    )
    app.include_router(config_router)
    app.include_router(session_router)
    app.include_router(skin_router)
    app.include_router(tts_router)
    app.include_router(memory_router)
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
        _DEV_WS_SENDERS.append(ws.send_json)
        # 注意力引擎（M-D）：[agent].attention=auto 才创建协调器；off（默认）
        # 时 companion.signal 直接忽略——M-C 结束点行为零变更（验收项）
        coordinator: CompanionCoordinator | None = None
        pump_task: asyncio.Task[None] | None = None
        resolved_cfg = _resolve_app_config(app)
        if resolved_cfg is not None and resolved_cfg.agent.attention == "auto":
            engine = AttentionEngine(settings_from_config(resolved_cfg.attention))
            coordinator = CompanionCoordinator(
                engine,
                manager,
                ws.send_json,
                store=app.state.store,
                session_id=getattr(app.state, "attention_session_id", "default"),
            )
            manager.attach_coordinator(coordinator)
            pump_task = asyncio.create_task(start_pump_loop(coordinator))
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
                except (ValueError, json.JSONDecodeError):
                    logger.warning("收到非法非 JSON 帧，忽略")
                    continue

                if frame is not None and isinstance(frame, dict):
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

                elif msg_type == "companion.signal":
                    # 陪伴信号（M-D）：off → 忽略（验收：关闭即 M-C 行为）
                    if not handshaken or coordinator is None:
                        continue
                    try:
                        payload = CompanionSignalData.model_validate(frame["data"])
                        await coordinator.handle_signal(payload)
                    except ValidationError:
                        logger.warning("命令负载校验失败：%s %s", msg_type, frame.get("data"))
                    except KeyError:
                        logger.warning("命令缺少 data：%s", msg_type)

                elif msg_type == "tool.confirm":
                    # 危险工具确认（6.5，M1-S4）：唤醒挂起中的回合。
                    # agent_source 可能是实例（显式注入）或零参可调用（registry 热切换）
                    if not handshaken:
                        continue
                    try:
                        payload = ToolConfirmData.model_validate(frame["data"])
                        agent = agent_source() if callable(agent_source) else agent_source
                        if isinstance(agent, LLMAgentService):
                            accepted = await agent.confirm(
                                payload.run_id,
                                payload.tool_call_id,
                                payload.decision,
                                remember=payload.remember,
                            )
                            if not accepted:
                                logger.warning(
                                    "确认不匹配等待中的调用，忽略：run=%s tc=%s",
                                    payload.run_id,
                                    payload.tool_call_id,
                                )
                        else:
                            logger.warning(
                                "当前 Agent 不支持工具确认（%s），忽略", type(agent).__name__
                            )
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
            if pump_task is not None:
                pump_task.cancel()
            return
        finally:
            with contextlib.suppress(ValueError):
                _DEV_WS_SENDERS.remove(ws.send_json)
            if pump_task is not None:
                pump_task.cancel()

    @app.post("/dev/cue", dependencies=[Depends(localhost_only)])
    async def dev_trigger_cue(request: Request) -> dict[str, Any]:
        """调试端点（非协议面）：向所有 ws 连接广播 character.cue，驱动角色表演。

        与业务路径同形：source=proactive、动作白名单强校验（越权丢弃）、
        immediate/replace/10s ttl。GUI 实测与手工验证用（curl POST {"actionId": "nod"}）。
        """
        try:
            body = await request.json()
        except Exception:
            return {"ok": False, "error": "body 不是合法 JSON"}
        action_id = str(body.get("actionId", "")).strip()
        channel = str(body.get("channel", "body")).strip()
        # 通道化白名单强校验（I3 起 locomotion 同样只收词表内 id）
        face_ids = frozenset(e.value for e in Emotion)
        whitelist: dict[str, frozenset[str]] = {
            "body": frozenset(SEMANTIC_ACTIONS),
            "face": face_ids,
            "locomotion": frozenset(LOCOMOTION_ACTIONS),
        }
        if channel not in whitelist:
            return {
                "ok": False,
                "error": f"未知通道：{channel or '(空)'}（可选 body/face/locomotion）",
            }
        if action_id not in whitelist[channel]:
            return {
                "ok": False,
                "error": f"{channel} 通道未知动作（不在词表）：{action_id or '(空)'}",
            }
        if channel == "face":
            channels = CueChannels(face=CueFaceChannel(emotion=action_id, intensity=0.9))
        elif channel == "locomotion":
            channels = CueChannels(locomotion=CueLocomotionChannel(action_id=action_id))
        else:
            channels = CueChannels(body=CueBodyChannel(action_id=action_id))
        frame = make_frame(
            EVENT_TYPES["character.cue"],
            CharacterCueData(
                cue_id=f"c-{uuid.uuid4().hex[:12]}",
                run_id=None,
                source="proactive",
                channels=channels,
                sync="immediate",
                priority=30,
                interrupt_policy="replace",
                ttl_ms=10_000,
            ),
            _now_ms(),
        )
        sent = 0
        for send in list(_DEV_WS_SENDERS):
            with contextlib.suppress(Exception):
                await send(frame)
                sent += 1
        logger.info("dev/cue 广播：%s → %d 连接", action_id, sent)
        return {"ok": True, "actionId": action_id, "sent": sent}

    return app


app = create_app()
