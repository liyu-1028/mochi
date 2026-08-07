"""TTS 引擎降级链与缓存测试（M1-S2， monkeypatch 禁联网）。"""

from __future__ import annotations

import pytest

from mochi_server.tts import TTSEngineError, edge_engine, local_engine
from mochi_server.tts.cache import TTSCache, make_key
from mochi_server.tts.engine import ENGINE_FALLBACK, synthesize
from mochi_server.tts.voices import is_known_voice, voice_catalog


@pytest.fixture(autouse=True)
def _clean_cache():
    from mochi_server.tts import cache as cache_mod

    cache_mod.CACHE = cache_mod.TTSCache()
    yield
    cache_mod.CACHE = cache_mod.TTSCache()


def _patch_edge(monkeypatch, result=b"MP3"):
    calls = {"n": 0}

    async def fake(text, voice_id, rate, volume):
        calls["n"] += 1
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(edge_engine, "synthesize", fake)
    return calls


def _patch_local(monkeypatch, result=b"WAV"):
    calls = {"n": 0}

    async def fake(text, rate):
        calls["n"] += 1
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(local_engine, "synthesize", fake)
    return calls


@pytest.mark.asyncio
async def test_edge_primary_success(monkeypatch):
    edge = _patch_edge(monkeypatch)
    local = _patch_local(monkeypatch)
    audio, engine, hit = await synthesize(
        "你好", voice_id="zh-CN-XiaoxiaoNeural", rate=1.0, volume=1.0, primary="edge"
    )
    assert (audio, engine, hit) == (b"MP3", "edge", False)
    assert edge["n"] == 1 and local["n"] == 0


@pytest.mark.asyncio
async def test_edge_fail_falls_back_to_local(monkeypatch):
    _patch_edge(monkeypatch, TTSEngineError("network down"))
    local = _patch_local(monkeypatch)
    audio, engine, _ = await synthesize(
        "你好", voice_id="zh-CN-XiaoxiaoNeural", rate=1.0, volume=1.0, primary="edge"
    )
    assert (audio, engine) == (b"WAV", "local")
    assert local["n"] == 1


@pytest.mark.asyncio
async def test_all_engines_fail_text_fallback(monkeypatch):
    _patch_edge(monkeypatch, TTSEngineError("network down"))
    _patch_local(monkeypatch, TTSEngineError("no say binary"))
    audio, engine, _ = await synthesize(
        "你好", voice_id="zh-CN-XiaoxiaoNeural", rate=1.0, volume=1.0, primary="edge"
    )
    assert (audio, engine) == (b"", ENGINE_FALLBACK)


@pytest.mark.asyncio
async def test_cache_hit_avoids_resynthesis(monkeypatch):
    edge = _patch_edge(monkeypatch)
    kwargs = dict(voice_id="zh-CN-XiaoxiaoNeural", rate=1.0, volume=1.0, primary="edge")
    first = await synthesize("缓存", **kwargs)
    second = await synthesize("缓存", **kwargs)
    assert first[2] is False and second[2] is True
    assert second[0] == b"MP3" and second[1] == "edge"
    assert edge["n"] == 1
    # 参数变化 → 新 key
    third = await synthesize("缓存", **{**kwargs, "rate": 1.5})
    assert third[2] is False and edge["n"] == 2


@pytest.mark.asyncio
async def test_unknown_primary_defaults_to_edge(monkeypatch):
    edge = _patch_edge(monkeypatch)
    await synthesize("x", voice_id="zh-CN-XiaoxiaoNeural", rate=1.0, volume=1.0, primary="bogus")
    assert edge["n"] == 1


def test_edge_pct_mapping():
    assert edge_engine._pct(1.0) == "+0%"
    assert edge_engine._pct(2.0) == "+100%"
    assert edge_engine._pct(0.5) == "-50%"


def test_cache_lru_and_ttl():
    cache = TTSCache(max_items=2, ttl=600)
    cache.put("a", b"1", "edge")
    cache.put("b", b"2", "edge")
    cache.put("c", b"3", "edge")  # 挤出 a
    assert cache.get("a") is None
    assert cache.get("b") == (b"2", "edge")
    expired = TTSCache(max_items=2, ttl=0)
    expired.put("k", b"v", "edge")
    assert expired.get("k") is None


def test_make_key_stable():
    assert make_key("t", "v", 1.0, 1.0) == make_key("t", "v", 1.0, 1.0)
    assert make_key("t", "v", 1.0, 1.0) != make_key("t2", "v", 1.0, 1.0)


def test_voice_catalog():
    catalog = voice_catalog()
    assert len(catalog) >= 2
    assert is_known_voice("zh-CN-XiaoxiaoNeural")
    assert not is_known_voice("nope")
