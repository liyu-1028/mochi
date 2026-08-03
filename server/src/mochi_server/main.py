"""FastAPI 入口：/health + /ws（协议 v0.1 握手骨架）。

TODO(M0)：
- 接入 LangGraph 认知核心（对话节点、工具调用框架）；
- chat.send → Agent 事件流的完整管线；
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
    Envelope,
    ErrorCode,
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
                # 握手：v0.1 直接接受；不兼容版本回 hello_error 并关闭
                requested: list[str] = frame.get("data", {}).get("versions", [])
                if PROTOCOL_VERSION in requested:
                    ack = Envelope(
                        type=EVENT_TYPES["hello_ack"],
                        ts=_now_ms(),
                        data={
                            "version": PROTOCOL_VERSION,
                            "server": {"name": SERVER_NAME, "version": __version__},
                        },
                    )
                    await ws.send_json(
                        ack.model_dump(mode="json", by_alias=True, exclude_none=True)
                    )
                else:
                    err = Envelope(
                        type=EVENT_TYPES["hello_error"],
                        ts=_now_ms(),
                        data={
                            "error": {
                                "code": ErrorCode.VERSION_MISMATCH,
                                "message": f"协议版本不兼容：客户端 {requested}，"
                                f"服务端支持 {PROTOCOL_VERSION}",
                                "retryable": False,
                                "hint": "请更新 Mochi 到最新版本",
                            }
                        },
                    )
                    await ws.send_json(
                        err.model_dump(mode="json", by_alias=True, exclude_none=True)
                    )
                    await ws.close()
                    return

            elif msg_type == "ping":
                pong = Envelope(
                    type=EVENT_TYPES["pong"],
                    ts=_now_ms(),
                    data={"token": frame.get("data", {}).get("token")},
                )
                await ws.send_json(
                    pong.model_dump(mode="json", by_alias=True, exclude_none=True)
                )

            elif msg_type in ("chat.send", "chat.cancel", "chat.interrupt"):
                # TODO(M0)：接入 LangGraph 认知核心后实现完整回合管线
                pass

    except WebSocketDisconnect:
        return
