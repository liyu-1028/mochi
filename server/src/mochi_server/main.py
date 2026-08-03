"""FastAPI 入口：/health + /ws（协议 v0.1 事件流）。

TODO(M0-S2)：
- 接入 LangGraph 认知核心（对话节点、工具调用框架）；
- 配置读写 RPC（HTTP 端点）；
- sidecar 端口发现机制（写 <userData>/runtime.json 供桌面壳读取）。
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from . import __version__
from .agent import EchoAgentService, RunManager
from .agent.service import AgentService
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

logger = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


def create_app(agent: AgentService | None = None) -> FastAPI:
    """应用工厂：agent 可注入（测试用零延迟桩；默认 echo 桩带拟真延迟）。"""
    app = FastAPI(title="mochi-server", version=__version__)
    app.state.agent = agent or EchoAgentService()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "protocol": PROTOCOL_VERSION}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        manager = RunManager(app.state.agent, ws.send_json)
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
                            # TODO(S2)：interrupt 与 cancel 语义分离（停止播报 vs 丢弃生成）
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
