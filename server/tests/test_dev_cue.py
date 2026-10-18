"""POST /dev/cue 调试端点：白名单校验与 ws 广播（M-D 验证辅助）。"""

from fastapi.testclient import TestClient

from mochi_server.config import AppConfig
from mochi_server.main import create_app


def _hello(ws: object) -> None:
    ws.send_json(  # type: ignore[attr-defined]
        {
            "v": "0.1",
            "type": "hello",
            "id": "1",
            "ts": 0,
            "data": {"versions": ["0.1"], "client": {"name": "t", "version": "0"}},
        }
    )
    ws.receive_json()  # type: ignore[attr-defined]  # hello_ack


def test_dev_cue_rejects_unknown_action() -> None:
    app = create_app(config=AppConfig())
    with TestClient(app) as client:
        r = client.post("/dev/cue", json={"actionId": "fly_to_moon"})
        assert r.status_code == 200
        assert r.json()["ok"] is False


def test_dev_cue_channel_whitelists() -> None:
    """通道化白名单（I3 起）：face/locomotion 各自词表校验，越权丢弃。"""
    app = create_app(config=AppConfig())
    with TestClient(app) as client:
        # 已删除的位置指令不得再通过调试入口触发
        for action_id in ("come_back", "lean_edge", "peek_dock", "lean_bubble", "peek_out"):
            r = client.post("/dev/cue", json={"channel": "locomotion", "actionId": action_id})
            assert r.json()["ok"] is False
        # locomotion 越权（body 词表 id 不在 locomotion 表）
        r = client.post("/dev/cue", json={"channel": "locomotion", "actionId": "nod"})
        assert r.json()["ok"] is False
        # face 合法 / 非法
        r = client.post("/dev/cue", json={"channel": "face", "actionId": "happy"})
        assert r.json()["ok"] is True
        r = client.post("/dev/cue", json={"channel": "face", "actionId": "nod"})
        assert r.json()["ok"] is False
        # 未知通道
        r = client.post("/dev/cue", json={"channel": "voice", "actionId": "nod"})
        assert r.json()["ok"] is False


def test_dev_cue_registered_locomotion_still_broadcasts(monkeypatch) -> None:
    """保留位置动作通道：未来注册的新指令仍可校验并广播。"""
    monkeypatch.setattr("mochi_server.main.LOCOMOTION_ACTIONS", ("test_position",))
    app = create_app(config=AppConfig())
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        _hello(ws)
        r = client.post("/dev/cue", json={"channel": "locomotion", "actionId": "test_position"})
        assert r.json() == {"ok": True, "actionId": "test_position", "sent": 1}
        frame = ws.receive_json()
        assert frame["type"] == "character.cue"
        assert frame["data"]["channels"]["locomotion"]["actionId"] == "test_position"


def test_dev_cue_broadcasts_to_ws_clients() -> None:
    app = create_app(config=AppConfig())
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        _hello(ws)
        r = client.post("/dev/cue", json={"actionId": "nod"})
        assert r.json() == {"ok": True, "actionId": "nod", "sent": 1}
        frame = ws.receive_json()
        assert frame["type"] == "character.cue"
        cue = frame["data"]
        assert cue["source"] == "proactive"
        assert cue["channels"]["body"]["actionId"] == "nod"
        assert cue["sync"] == "immediate"
