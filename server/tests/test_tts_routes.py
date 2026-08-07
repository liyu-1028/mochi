"""TTS 端点契约测试（M1-S2）：流式/降级/静音/校验/音色目录。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mochi_server.config import AppConfig
from mochi_server.main import create_app
from mochi_server.tts import TTSEngineError, edge_engine


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app(config=AppConfig())) as c:
        yield c


@pytest.fixture(autouse=True)
def _patch_edge(monkeypatch):
    async def fake(text, voice_id, rate, volume):
        return b"FAKEMP3"

    monkeypatch.setattr(edge_engine, "synthesize", fake)


def test_stream_success_headers_and_body(client):
    resp = client.post("/tts/stream", json={"text": "你好世界"})
    assert resp.status_code == 200
    assert resp.content == b"FAKEMP3"
    assert resp.headers["X-TTS-Engine"] == "edge"
    assert resp.headers["X-TTS-Cache"] == "miss"
    assert resp.headers["content-type"].startswith("audio/mpeg")
    # 同参数二次请求命中缓存
    again = client.post("/tts/stream", json={"text": "你好世界"})
    assert again.headers["X-TTS-Cache"] == "hit"


def test_stream_empty_text_204(client):
    resp = client.post("/tts/stream", json={"text": "   "})
    assert resp.status_code == 204


def test_stream_too_long_400(client):
    resp = client.post("/tts/stream", json={"text": "长" * 5001})
    assert resp.status_code == 400
    assert "5000" in resp.json()["detail"]


def test_stream_unknown_voice_400(client):
    resp = client.post("/tts/stream", json={"text": "你好", "voiceId": "nope"})
    assert resp.status_code == 400


def test_stream_muted_204(client):
    client.put("/config/voice", json={"muted": True})
    resp = client.post("/tts/stream", json={"text": "你好"})
    assert resp.status_code == 204
    assert resp.headers["X-TTS-Engine"] == "muted"


def test_stream_disabled_204(client):
    client.put("/config/voice", json={"ttsEnabled": False})
    resp = client.post("/tts/stream", json={"text": "你好"})
    assert resp.status_code == 204


def test_stream_engine_fail_text_fallback_204(client, monkeypatch):
    async def broken(text, voice_id, rate, volume):
        raise TTSEngineError("down")

    monkeypatch.setattr(edge_engine, "synthesize", broken)
    from mochi_server.tts import local_engine

    async def no_local(text, rate):
        raise TTSEngineError("unsupported")

    monkeypatch.setattr(local_engine, "synthesize", no_local)
    resp = client.post("/tts/stream", json={"text": "你好"})
    assert resp.status_code == 204
    assert resp.headers["X-TTS-Engine"] == "text-fallback"


def test_voices_catalog(client):
    resp = client.get("/tts/voices")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["voices"]) >= 2
    assert body["default"] == "zh-CN-XiaoxiaoNeural"
