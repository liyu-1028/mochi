"""FastAPI 入口：/health + /ws（协议 v0.1 握手骨架）。

TODO(M0-S2)：
- 接入 LangGraph 认知核心（对话节点、工具调用框架）；
- 配置读写 RPC（HTTP 端点）；
- sidecar 端口发现机制（写 <userData>/runtime.json 供桌面壳读取）。
"""

from __future__ import annotations

import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from . import __version__
from .events import (
    EVENT_TYPES,
    PROTOCOL_VERSION,
    SERVER_NAME,
    ErrorCode,
    ErrorPayload,
    HelloAckData,
    HelloData,
    HelloErrorData,
    PongData,
    ServerInfo,
    make_frame,
)

app = FastAPI(title="mochi-server", version=__version__)


def _now_ms() -> int:
    return int(time.time() * 1000)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__, "protocol": PROTOCOL_VERSION}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
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
                # TODO(M0-S1)：接入 RunManager 后实现完整回合管线
                pass

    except WebSocketDisconnect:
        return
