"""皮肤 REST 端点测试（M1-S1）：列表/删除/active 回退/用户资源分发。"""

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


def _write_user_skin(skin_id: str, filename: str = "avatar.png") -> None:
    skin_dir = get_skins_dir() / skin_id
    skin_dir.mkdir(parents=True, exist_ok=True)
    (skin_dir / filename).write_bytes(b"png-bytes")
    manifest = {"id": skin_id, "name": skin_id, "resourceType": "static", "imageFile": filename}
    (skin_dir / "skin.json").write_text(json.dumps(manifest), encoding="utf-8")


# ---------------------------------------------------------------------------
# GET /skins
# ---------------------------------------------------------------------------


def test_list_skins_includes_builtins(client):
    resp = client.get("/skins")
    assert resp.status_code == 200
    skins = resp.json()
    ids = {s["id"] for s in skins}
    assert {"hiyori", "mochi-julia", "mochi-snj"} <= ids
    hiyori = next(s for s in skins if s["id"] == "hiyori")
    assert hiyori["source"] == "builtin"
    assert hiyori["resourceBaseUrl"] == "/skins/hiyori"


def test_list_skins_includes_user_with_absolute_base_url(client):
    _write_user_skin("mycat")
    resp = client.get("/skins")
    mycat = next((s for s in resp.json() if s["id"] == "mycat"), None)
    assert mycat is not None
    assert mycat["source"] == "user"
    assert mycat["resourceBaseUrl"].startswith("http://127.0.0.1:")
    assert mycat["resourceBaseUrl"].endswith("/user-skins/mycat")


# ---------------------------------------------------------------------------
# DELETE /skins/{id}
# ---------------------------------------------------------------------------


def test_delete_builtin_forbidden(client):
    assert client.delete("/skins/hiyori").status_code == 403


def test_delete_unknown_404(client):
    assert client.delete("/skins/nope").status_code == 404


def test_delete_user_skin(client):
    _write_user_skin("gone")
    assert client.delete("/skins/gone").status_code == 204
    assert not any(s["id"] == "gone" for s in client.get("/skins").json())


def test_delete_active_skin_falls_back_to_default(client):
    _write_user_skin("doomed")
    assert client.put("/config/character", json={"activeSkin": "doomed"}).status_code == 200

    assert client.delete("/skins/doomed").status_code == 204
    assert client.get("/config/character").json()["activeSkin"] == "default"


# ---------------------------------------------------------------------------
# GET /user-skins/{id}/{path}
# ---------------------------------------------------------------------------


def test_user_skin_file_served(client):
    _write_user_skin("served")
    resp = client.get("/user-skins/served/avatar.png")
    assert resp.status_code == 200
    assert resp.content == b"png-bytes"


def test_user_skin_file_missing_404(client):
    assert client.get("/user-skins/nobody/avatar.png").status_code == 404


def test_user_skin_path_traversal_blocked(client):
    _write_user_skin("trav")
    # %2e%2e 经路由解码为 ..（裸 .. 会被 httpx 客户端规范化掉）：
    # 解出 base 之外必须 404
    resp = client.get("/user-skins/trav/%2e%2e/%2e%2e/config.toml")
    assert resp.status_code == 404
