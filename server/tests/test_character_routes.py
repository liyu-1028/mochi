"""GET/PUT /config/character 端点测试（M1-S1，3.3 换肤持久化）。

内置静态皮肤下线后：默认 activeSkin=""（未设置）；
PUT 仍要求皮肤已导入（422 防拼写错误），空串用于清空选择。
"""

from __future__ import annotations

import json
import tomllib

import pytest
from fastapi.testclient import TestClient

from mochi_server.config import AppConfig
from mochi_server.main import create_app
from mochi_server.paths import get_config_path, get_skins_dir


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app(config=AppConfig())) as c:
        yield c


def _write_user_skin(skin_id: str) -> None:
    skin_dir = get_skins_dir() / skin_id
    skin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": skin_id,
        "name": skin_id,
        "resourceType": "live2d",
        "modelFile": "m.model3.json",
    }
    (skin_dir / "skin.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_get_character_default(client):
    resp = client.get("/config/character")
    assert resp.status_code == 200
    assert resp.json() == {"activeSkin": ""}


def test_put_character_persists(client):
    _write_user_skin("mycat")
    resp = client.put("/config/character", json={"activeSkin": "mycat"})
    assert resp.status_code == 200
    assert resp.json() == {"activeSkin": "mycat"}

    # 落盘校验（config.toml 为 snake_case 原始 dump，既有约定）
    raw = tomllib.load(get_config_path().open("rb"))
    assert raw["character"]["active_skin"] == "mycat"


def test_put_character_unknown_skin_422(client):
    resp = client.put("/config/character", json={"activeSkin": "nope"})
    assert resp.status_code == 422
    assert "nope" in resp.json()["detail"]


def test_put_character_empty_clears(client):
    """空串 = 清空选择（删除当前皮肤时的回退语义）。"""
    _write_user_skin("mycat")
    assert client.put("/config/character", json={"activeSkin": "mycat"}).status_code == 200

    resp = client.put("/config/character", json={"activeSkin": ""})
    assert resp.status_code == 200
    assert resp.json() == {"activeSkin": ""}
    raw = tomllib.load(get_config_path().open("rb"))
    assert raw["character"]["active_skin"] == ""


def test_put_character_empty_body_noop(client):
    resp = client.put("/config/character", json={})
    assert resp.status_code == 200
    assert resp.json() == {"activeSkin": ""}
