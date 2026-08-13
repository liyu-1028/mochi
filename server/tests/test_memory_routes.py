"""记忆 REST 端点测试（M1-S3，功能清单 6.4）：列表/创建/编辑/删除/清空。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mochi_server.config import AppConfig
from mochi_server.main import create_app


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app(config=AppConfig())) as c:
        yield c


def test_list_empty(client):
    resp = client.get("/memories")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_and_list(client):
    resp = client.post("/memories", json={"content": "用户喜欢猫", "category": "preference"})
    assert resp.status_code == 201
    item = resp.json()
    assert item["content"] == "用户喜欢猫"
    assert item["category"] == "preference"
    assert item["source"] == "manual"

    resp = client.get("/memories")
    assert len(resp.json()) == 1


def test_create_invalid_category_falls_back(client):
    resp = client.post("/memories", json={"content": "x", "category": "weird"})
    assert resp.status_code == 201
    assert resp.json()["category"] == "fact"


def test_update_memory(client):
    item = client.post("/memories", json={"content": "旧"}).json()
    resp = client.put(f"/memories/{item['id']}", json={"content": "新"})
    assert resp.status_code == 200
    assert resp.json()["content"] == "新"


def test_update_nonexistent_404(client):
    assert client.put("/memories/nope", json={"content": "x"}).status_code == 404


def test_delete_memory(client):
    item = client.post("/memories", json={"content": "bye"}).json()
    assert client.delete(f"/memories/{item['id']}").status_code == 204
    assert client.delete(f"/memories/{item['id']}").status_code == 404


def test_clear_all(client):
    client.post("/memories", json={"content": "a"})
    client.post("/memories", json={"content": "b"})
    assert client.delete("/memories").status_code == 204
    assert client.get("/memories").json() == []


def test_list_by_category(client):
    client.post("/memories", json={"content": "f", "category": "fact"})
    client.post("/memories", json={"content": "p", "category": "preference"})
    resp = client.get("/memories?category=preference")
    assert len(resp.json()) == 1
    assert resp.json()[0]["category"] == "preference"
