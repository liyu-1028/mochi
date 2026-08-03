"""WebSocket 端到端集成测试：握手 → 完整回合 → 取消（FastAPI TestClient）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from mochi_server.agent import EchoAgentService
from mochi_server.config import AppConfig, ModelConfig, ModelProviderConfig
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


def test_registry_driven_turn_via_config_injection() -> None:
    """S2 生产装配路径：config 注入 → registry 按回合解析 agent（此例为试用模式）。"""
    app = create_app(config=AppConfig())  # 默认 default_provider=trial
    assert app.state.registry is not None
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json(_hello())
        assert ws.receive_json()["type"] == "hello_ack"

        ws.send_json(_chat_send())
        frames = _drain_until_finished(ws)
        assert frames[-1]["data"]["reason"] == "complete"
        assert any(f["type"] == "text.end" for f in frames)


def test_registry_missing_key_surfaces_run_error() -> None:
    """default provider 缺 Key：不崩溃，run.error 带引导文案 + error 状态。"""
    config = AppConfig(
        model=ModelConfig(
            default_provider="cloud",
            providers={
                "cloud": ModelProviderConfig(
                    kind="openai_compatible",
                    display_name="云端",
                    base_url="https://api.example.com/v1",
                    model="m",
                )
            },
        )
    )
    app = create_app(config=config)
    app.state.error_recovery_delay_s = 0.05  # 测试加速：error → idle 恢复
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json(_hello())
        assert ws.receive_json()["type"] == "hello_ack"

        ws.send_json(_chat_send())
        frames = _drain_until_finished(ws)

        error_frames = [f for f in frames if f["type"] == "run.error"]
        assert len(error_frames) == 1
        assert error_frames[0]["data"]["error"]["code"] == "ERR_MODEL_AUTH"
        assert frames[-1]["data"]["reason"] == "error"
        # 出错回合：run.error 后紧跟 state.change(error)（2.2）
        states = [f["data"]["state"] for f in frames if f["type"] == "state.change"]
        assert "error" in states

        # 延迟恢复：继续收帧直到 state.change(idle)
        for _ in range(20):
            frame = ws.receive_json()
            if frame["type"] == "state.change" and frame["data"]["state"] == "idle":
                break
        else:
            raise AssertionError("未等到 error → idle 恢复帧")


def test_sleeping_after_idle_threshold_and_wake() -> None:
    """长时间无业务帧 → sleeping（2.2）；业务帧唤醒回 idle。"""
    app = create_app(EchoAgentService(chunk_delay=0, thinking_delay=0))
    app.state.sleep_threshold_s = 0.1  # 测试加速
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json(_hello())
        assert ws.receive_json()["type"] == "hello_ack"

        # 不再发任何业务帧：应收到 state.change(sleeping)
        for _ in range(50):
            frame = ws.receive_json()
            if frame["type"] == "state.change" and frame["data"]["state"] == "sleeping":
                break
        else:
            raise AssertionError("未等到 sleeping 状态帧")

        # 业务帧唤醒：先发 idle 再处理命令
        ws.send_json(_chat_send())
        woke = ws.receive_json()
        assert woke["type"] == "state.change"
        assert woke["data"]["state"] == "idle"
        frames = _drain_until_finished(ws)
        assert frames[-1]["data"]["reason"] == "complete"


def test_ping_does_not_reset_idle_timer() -> None:
    """ping 心跳不计入活跃度：持续心跳下仍会进入 sleeping。"""
    app = create_app(EchoAgentService(chunk_delay=0, thinking_delay=0))
    app.state.sleep_threshold_s = 0.15
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json(_hello())
        assert ws.receive_json()["type"] == "hello_ack"

        slept = False
        # 交替发 ping 与收帧；心跳不应阻止休眠
        for i in range(30):
            ws.send_json(
                {"v": "0.1", "type": "ping", "id": f"p-{i}", "ts": 0, "data": {"token": str(i)}}
            )
            frame = ws.receive_json()
            while frame["type"] == "pong":
                frame = ws.receive_json()
            if frame["type"] == "state.change" and frame["data"]["state"] == "sleeping":
                slept = True
                break
        assert slept, "持续 ping 心跳下未能进入 sleeping（心跳错误地重置了活跃度）"
