"""皮肤 REST 端点测试（M1-S1）：列表/删除/active 回退/用户资源分发。

内置静态皮肤已下线：列表只含用户导入的皮肤；
删除当前皮肤回退为清空选择（activeSkin=""）。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from mochi_server.config import AppConfig
from mochi_server.main import create_app
from mochi_server.paths import get_skins_dir


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app(config=AppConfig())) as c:
        yield c


def _write_user_skin(skin_id: str, filename: str = "m.model3.json") -> None:
    skin_dir = get_skins_dir() / skin_id
    skin_dir.mkdir(parents=True, exist_ok=True)
    (skin_dir / filename).write_bytes(b'{"type":"Model"}')
    manifest = {
        "id": skin_id,
        "name": skin_id,
        "resourceType": "live2d",
        "modelFile": filename,
    }
    (skin_dir / "skin.json").write_text(json.dumps(manifest), encoding="utf-8")


# ---------------------------------------------------------------------------
# GET /skins
# ---------------------------------------------------------------------------


def test_list_skins_builtin_by_default(client):
    """fresh install 只含 Mochi 内置 VRM 角色（ADR-0011），导入后用户皮肤追加在列表。"""
    skins = client.get("/skins").json()
    assert [s["id"] for s in skins] == ["mochi-vrm"]
    assert all(s["source"] == "builtin" for s in skins)

    _write_user_skin("mycat")
    skins = client.get("/skins").json()
    mycat = next((s for s in skins if s["id"] == "mycat"), None)
    assert mycat is not None
    assert mycat["source"] == "user"
    assert mycat["resourceBaseUrl"].startswith("http://127.0.0.1:")
    assert mycat["resourceBaseUrl"].endswith("/user-skins/mycat")
    # 渲染必需字段随列表下发（前端拼 URL / 选动作档案）
    assert mycat["modelFile"] == "m.model3.json"


# ---------------------------------------------------------------------------
# DELETE /skins/{id}
# ---------------------------------------------------------------------------


def test_delete_unknown_404(client):
    assert client.delete("/skins/nope").status_code == 404


def test_delete_user_skin(client):
    _write_user_skin("gone")
    assert client.delete("/skins/gone").status_code == 204
    assert not any(s["id"] == "gone" for s in client.get("/skins").json())


def test_delete_active_skin_falls_back_to_empty(client):
    _write_user_skin("doomed")
    assert client.put("/config/character", json={"activeSkin": "doomed"}).status_code == 200

    assert client.delete("/skins/doomed").status_code == 204
    assert client.get("/config/character").json()["activeSkin"] == ""


# ---------------------------------------------------------------------------
# GET /user-skins/{id}/{path}
# ---------------------------------------------------------------------------


def test_user_skin_file_served(client):
    _write_user_skin("served")
    resp = client.get("/user-skins/served/m.model3.json")
    assert resp.status_code == 200
    assert resp.content == b'{"type":"Model"}'


def test_user_skin_file_missing_404(client):
    assert client.get("/user-skins/nobody/m.model3.json").status_code == 404


def test_user_skin_path_traversal_blocked(client):
    _write_user_skin("trav")
    # %2e%2e 经路由解码为 ..（裸 .. 会被 httpx 客户端规范化掉）：
    # 解出 base 之外必须 404
    resp = client.get("/user-skins/trav/%2e%2e/%2e%2e/config.toml")
    assert resp.status_code == 404


def test_removed_builtin_is_unavailable_and_mochi_is_protected(client):
    assert client.put("/config/character", json={"activeSkin": "seed-san"}).status_code == 422
    assert client.delete("/skins/mochi-vrm").status_code == 403
    assert client.get("/config/character").json()["activeSkin"] == "mochi-vrm"


def test_removed_active_builtin_is_migrated_to_mochi():
    config = AppConfig()
    config.character.active_skin = "seed-san"
    with TestClient(create_app(config=config)) as client:
        assert client.get("/config/character").json()["activeSkin"] == "mochi-vrm"
        assert [s["id"] for s in client.get("/skins").json()] == ["mochi-vrm"]


def test_user_role_with_same_old_builtin_id_is_preserved():
    _write_user_skin("seed-san")
    config = AppConfig()
    config.character.active_skin = "seed-san"
    with TestClient(create_app(config=config)) as client:
        assert client.get("/config/character").json()["activeSkin"] == "seed-san"
