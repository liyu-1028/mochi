"""WebSocket 端到端集成测试：握手 → 完整回合 → 取消（FastAPI TestClient）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from mochi_server.agent import EchoAgentService
from mochi_server.events import PROTOCOL_VERSION
from mochi_server.main import create_app


def _client(chunk_delay: float = 0, thinking_delay: float = 0) -> TestClient:
    # 默认零延迟桩：集成测试秒级完成
    return TestClient(
        create_app(EchoAgentService(chunk_delay=chunk_delay, thinking_delay=thinking_delay))
    )


def _hello(versions: list[str] | None = None) -> dict:
    return {
        "v": "0.1",
        "type": "hello",
        "id": "c-hello",
        "ts": 0,
        "data": {
            "versions": versions or ["0.1"],
            "client": {"name": "pytest", "version": "0.0.0"},
        },
    }


def _chat_send(run_id: str = "r-it") -> dict:
    return {
        "v": "0.1",
        "type": "chat.send",
        "id": "c-send",
        "ts": 0,
        "data": {"runId": run_id, "sessionId": "s-it", "text": "你好，Mochi"},
    }


def _drain_until_finished(ws, limit: int = 300) -> list[dict]:
    frames = []
    for _ in range(limit):
        frame = ws.receive_json()
        frames.append(frame)
        if frame["type"] == "run.finished":
            return frames
    raise AssertionError("超过帧数上限仍未收到 run.finished")


def test_health_endpoint() -> None:
    resp = _client().get("/health")
    assert resp.status_code == 200
    assert resp.json()["protocol"] == PROTOCOL_VERSION


def test_handshake_and_full_turn() -> None:
    """握手 → chat.send → 流式回合 → run.finished(complete)。"""
    with _client().websocket_connect("/ws") as ws:
        ws.send_json(_hello())
        ack = ws.receive_json()
        assert ack["type"] == "hello_ack"
        assert ack["data"]["version"] == PROTOCOL_VERSION

        ws.send_json(_chat_send())
        frames = _drain_until_finished(ws)

        types = [f["type"] for f in frames]
        assert types[0] == "run.started"
        assert "thinking.start" in types and "thinking.end" in types
        assert "text.start" in types and "text.end" in types
        assert "state.change" in types and "emotion" in types

        full = "".join(f["data"]["delta"] for f in frames if f["type"] == "text.delta")
        end = next(f for f in frames if f["type"] == "text.end")
        assert full == end["data"]["fullText"]
        assert frames[-1]["data"]["reason"] == "complete"


def test_version_mismatch_rejected() -> None:
    with _client().websocket_connect("/ws") as ws:
        ws.send_json(_hello(versions=["9.9"]))
        err = ws.receive_json()
        assert err["type"] == "hello_error"
        assert err["data"]["error"]["code"] == "ERR_VERSION_MISMATCH"


def test_chat_before_handshake_ignored() -> None:
    """握手前发送业务命令应被忽略（协议 §2）。"""
    with _client().websocket_connect("/ws") as ws:
        ws.send_json(_chat_send())  # 未握手，应被丢弃
        ws.send_json(_hello())
        ack = ws.receive_json()
        assert ack["type"] == "hello_ack"  # 第一帧只能是握手应答


def test_cancel_via_ws() -> None:
    with _client(chunk_delay=0.05, thinking_delay=0.05).websocket_connect("/ws") as ws:
        ws.send_json(_hello())
        assert ws.receive_json()["type"] == "hello_ack"

        ws.send_json(_chat_send())
        ws.send_json(
            {
                "v": "0.1",
                "type": "chat.cancel",
                "id": "c-cancel",
                "ts": 0,
                "data": {"runId": "r-it"},
            }
        )
        frames = _drain_until_finished(ws)
        assert frames[-1]["data"]["reason"] == "cancelled"
