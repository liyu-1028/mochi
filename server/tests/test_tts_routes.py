"""TTS 路由语义矩阵测试（ADR-0007 修订；monkeypatch 禁联网）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mochi_server.config import AppConfig, ModelConnectionConfig
from mochi_server.main import create_app
from mochi_server.tts import TTSEngineError


@pytest.fixture(autouse=True)
def _clean_cache():
    from mochi_server.tts import cache as cache_mod

    cache_mod.CACHE = cache_mod.TTSCache()
    yield
    cache_mod.CACHE = cache_mod.TTSCache()


@pytest.fixture
def client():
    with TestClient(create_app(config=AppConfig())) as c:
        yield c


def _bind_connection(client: TestClient) -> None:
    """写入百炼连接 + Key（内存钥匙串），返回绑定状态。"""
    registry = client.app.state.registry
    registry.key_store.set_key("bailian-voice", "sk-test")
    config = registry.config.model_copy(deep=True)
    config.model.connections["bailian-voice"] = ModelConnectionConfig(
        preset_id="dashscope",
        display_name="百炼（语音）",
        endpoints={},
    )
    config.voice.connection_id = "bailian-voice"
    registry.update_config(config)


def _patch_cloud(monkeypatch, result=b"MP3"):
    async def fake(text, *, voice_id, rate, conn):
        if isinstance(result, Exception):
            raise result
        return result

    from mochi_server.tts import cosyvoice_engine

    monkeypatch.setattr(cosyvoice_engine, "synthesize", fake)


def test_stream_disabled_204(client):
    resp = client.post("/tts/stream", json={"text": "你好"})  # tts_enabled 默认 False
    assert resp.status_code == 204
    assert resp.headers["X-TTS-Engine"] == "muted"


def test_stream_empty_text_204(client):
    client.put("/config/voice", json={"ttsEnabled": True})
    resp = client.post("/tts/stream", json={"text": "   "})
    assert resp.status_code == 204
    assert resp.headers["X-TTS-Engine"] == "text-fallback"


def test_stream_too_long_400(client):
    client.put("/config/voice", json={"ttsEnabled": True})
    resp = client.post("/tts/stream", json={"text": "x" * 5001})
    assert resp.status_code == 400


def test_stream_unconfigured_204_cloud_unconfigured(client):
    """未绑定连接：204 + cloud-unconfigured（新语义，前端引导配置而非报错）。"""
    client.put("/config/voice", json={"ttsEnabled": True})
    resp = client.post("/tts/stream", json={"text": "你好"})
    assert resp.status_code == 204
    assert resp.headers["X-TTS-Engine"] == "cloud-unconfigured"


def test_stream_privacy_local_only_204(client):
    registry = client.app.state.registry
    config = registry.config.model_copy(deep=True)
    config.privacy.local_only = True
    registry.update_config(config)
    client.put("/config/voice", json={"ttsEnabled": True})
    resp = client.post("/tts/stream", json={"text": "你好"})
    assert resp.status_code == 204
    assert resp.headers["X-TTS-Engine"] == "cloud-unconfigured"


def test_stream_success_headers_and_body(client, monkeypatch):
    _patch_cloud(monkeypatch, b"MP3-DATA")
    _bind_connection(client)
    client.put("/config/voice", json={"ttsEnabled": True})
    resp = client.post("/tts/stream", json={"text": "你好"})
    assert resp.status_code == 200
    assert resp.headers["X-TTS-Engine"] == "cosyvoice"
    assert resp.headers["X-TTS-Cache"] == "miss"
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.content == b"MP3-DATA"

    # 同文本二次请求命中缓存
    resp2 = client.post("/tts/stream", json={"text": "你好"})
    assert resp2.headers["X-TTS-Cache"] == "hit"


def test_stream_cloud_fail_text_fallback_204(client, monkeypatch):
    _patch_cloud(monkeypatch, TTSEngineError("down"))
    _bind_connection(client)
    client.put("/config/voice", json={"ttsEnabled": True})
    resp = client.post("/tts/stream", json={"text": "你好"})
    assert resp.status_code == 204
    assert resp.headers["X-TTS-Engine"] == "text-fallback"


def test_stream_legacy_voice_id_normalized(client, monkeypatch):
    """旧 edge 音色 id 经 normalize 落 CosyVoice；未知 id 不再 400（云端兜底）。"""
    seen = {}

    async def fake(text, *, voice_id, rate, conn):
        seen["voice_id"] = voice_id
        return b"MP3"

    from mochi_server.tts import cosyvoice_engine

    monkeypatch.setattr(cosyvoice_engine, "synthesize", fake)
    _bind_connection(client)
    client.put("/config/voice", json={"ttsEnabled": True, "voiceId": "zh-CN-XiaoxiaoNeural"})
    resp = client.post("/tts/stream", json={"text": "你好"})
    assert resp.status_code == 200
    assert seen["voice_id"] == "longxing_v3"

    # 复刻音色 mix_* 直传不拒
    resp = client.post("/tts/stream", json={"text": "你好", "voiceId": "mix_voice_abc"})
    assert resp.status_code == 200
    assert seen["voice_id"] == "mix_voice_abc"


def test_voices_catalog(client):
    resp = client.get("/tts/voices")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["voices"]) >= 30
    assert all("category" in v for v in body["voices"])
    assert body["default"] == "longxing_v3"
