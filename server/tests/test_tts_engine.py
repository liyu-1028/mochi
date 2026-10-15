"""TTS 引擎层测试（ADR-0007 修订：云端唯一引擎 + 纯文本降级；monkeypatch 禁联网）。"""

from __future__ import annotations

import pytest

from mochi_server.tts import TTSEngineError
from mochi_server.tts.cache import TTSCache, make_key
from mochi_server.tts.cosyvoice_engine import SpeechConnection
from mochi_server.tts.engine import ENGINE_FALLBACK, synthesize
from mochi_server.tts.voices import (
    DEFAULT_VOICE_ID,
    VOICES,
    normalize_voice_id,
    voice_catalog,
)

_CONN = SpeechConnection(connection_id="bailian-voice", api_key="sk")


@pytest.fixture(autouse=True)
def _clean_cache():
    from mochi_server.tts import cache as cache_mod

    cache_mod.CACHE = cache_mod.TTSCache()
    yield
    cache_mod.CACHE = cache_mod.TTSCache()


def _patch_cloud(monkeypatch, result=b"MP3"):
    calls = {"n": 0}

    async def fake(text, *, voice_id, rate, conn):
        calls["n"] += 1
        if isinstance(result, Exception):
            raise result
        return result

    from mochi_server.tts import cosyvoice_engine

    monkeypatch.setattr(cosyvoice_engine, "synthesize", fake)
    return calls


@pytest.mark.asyncio
async def test_cloud_success_returns_mp3(monkeypatch):
    _patch_cloud(monkeypatch)
    audio, used, hit = await synthesize("你好", voice_id="longxing_v3", rate=1.0, conn=_CONN)
    assert audio == b"MP3"
    assert used == "cosyvoice"
    assert hit is False


@pytest.mark.asyncio
async def test_cloud_fail_falls_back_to_text(monkeypatch):
    _patch_cloud(monkeypatch, TTSEngineError("401"))
    audio, used, hit = await synthesize("你好", voice_id="longxing_v3", rate=1.0, conn=_CONN)
    assert audio == b""
    assert used == ENGINE_FALLBACK
    assert hit is False


@pytest.mark.asyncio
async def test_cache_hit_skips_cloud(monkeypatch):
    calls = _patch_cloud(monkeypatch)
    await synthesize("你好", voice_id="longxing_v3", rate=1.0, conn=_CONN)
    audio, used, hit = await synthesize("你好", voice_id="longxing_v3", rate=1.0, conn=_CONN)
    assert hit is True
    assert calls["n"] == 1  # 第二次命中缓存，不再打云端
    assert used == "cosyvoice"
    assert audio == b"MP3"


def test_make_key_stable():
    assert make_key("t", "v", 1.0) == make_key("t", "v", 1.0)
    assert make_key("t", "v", 1.0) != make_key("t2", "v", 1.0)
    assert make_key("t", "v", 1.0) != make_key("t", "v2", 1.0)


def test_cache_lru_and_ttl(monkeypatch):
    cache = TTSCache(max_items=2, ttl_seconds=100)
    cache.put("a", b"1", "cosyvoice")
    cache.put("b", b"2", "cosyvoice")
    cache.put("c", b"3", "cosyvoice")
    assert cache.get("a") is None  # LRU 淘汰
    assert cache.get("b") == (b"2", "cosyvoice")


def test_voice_catalog_and_normalize():
    catalog = voice_catalog()
    assert len(catalog) >= 30  # v3 全量目录（社交陪伴/助手/客服/方言/童声）
    assert {v["category"] for v in catalog} >= {
        "companion",
        "assistant",
        "support",
        "dialect",
        "child",
    }
    assert DEFAULT_VOICE_ID == "longxing_v3"
    assert all(v.id.startswith(("long", "loong")) for v in VOICES)
    # 旧 edge 音色映射
    assert normalize_voice_id("zh-CN-XiaoxiaoNeural") == "longxing_v3"
    assert normalize_voice_id("zh-CN-YunxiNeural") == "longanyang"
    # v2 目录（语音重构过渡期）→ v3；同名不同性别的坑（龙华 v2 男 → v3 女）
    assert normalize_voice_id("longwan_v2") == "longwan_v3"
    assert normalize_voice_id("longhua_v2") == "longtian_v3"
    # 未知 id 原样（兼容复刻音色 mix_*），空值回默认
    assert normalize_voice_id("mix_voice_abc") == "mix_voice_abc"
    assert normalize_voice_id("") == DEFAULT_VOICE_ID
