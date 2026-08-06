"""GET/PUT /config/character 端点测试（M1-S1，3.3 换肤持久化）。"""

from __future__ import annotations

import tomllib

import pytest
from fastapi.testclient import TestClient

from mochi_server.config import AppConfig
from mochi_server.main import create_app
from mochi_server.paths import get_config_path


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app(config=AppConfig())) as c:
        yield c


def test_get_character_default(client):
    resp = client.get("/config/character")
    assert resp.status_code == 200
    assert resp.json() == {"activeSkin": "default"}


def test_put_character_persists(client):
    resp = client.put("/config/character", json={"activeSkin": "mochi-julia"})
    assert resp.status_code == 200
    assert resp.json() == {"activeSkin": "mochi-julia"}

    # 落盘校验（config.toml 为 snake_case 原始 dump，既有约定）
    raw = tomllib.load(get_config_path().open("rb"))
    assert raw["character"]["active_skin"] == "mochi-julia"


def test_put_character_unknown_skin_422(client):
    resp = client.put("/config/character", json={"activeSkin": "nope"})
    assert resp.status_code == 422
    assert "nope" in resp.json()["detail"]


def test_put_character_empty_body_noop(client):
    resp = client.put("/config/character", json={})
    assert resp.status_code == 200
    assert resp.json() == {"activeSkin": "default"}
