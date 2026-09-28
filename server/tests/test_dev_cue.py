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
