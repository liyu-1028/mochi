"""CosyVoice 云端引擎测试（httpx MockTransport，禁联网）。"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from mochi_server.config import AppConfig, ModelConnectionConfig
from mochi_server.secrets import KeyStore
from mochi_server.tts import TTSEngineError, cosyvoice_engine
from mochi_server.tts.cosyvoice_engine import (
    SpeechConnection,
    probe,
    resolve_speech_connection,
    synthesize,
)

_CONN = SpeechConnection(connection_id="bailian-voice", api_key="sk-test")


def _install(monkeypatch, handler) -> httpx.MockTransport:
    """注入 MockTransport；顺带断言请求都带 Bearer Key。"""

    def checked(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/SpeechSynthesizer"):
            assert request.headers.get("Authorization") == "Bearer sk-test"
        else:  # 音频 URL 是临时 CDN 链接，绝不能把 Key 带过去
            assert "Authorization" not in request.headers
        return handler(request)

    transport = httpx.MockTransport(checked)
    monkeypatch.setattr(
        cosyvoice_engine, "_build_http_client", lambda: httpx.AsyncClient(transport=transport)
    )
    return transport


@pytest.mark.asyncio
async def test_synthesize_maps_params_and_downloads(monkeypatch):
    """原生布局：voice/format/rate 都在 input；非流式 URL 二次 GET。"""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/SpeechSynthesizer"):
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"output": {"audio": {"url": "https://cdn/a.mp3"}}})
        seen["download"] = str(request.url)
        return httpx.Response(200, content=b"MP3-BYTES")

    _install(monkeypatch, handler)
    audio = await synthesize("你好", voice_id="longxing_v3", rate=1.5, conn=_CONN)
    assert audio == b"MP3-BYTES"
    assert seen["body"] == {
        "model": "cosyvoice-v3-flash",
        "input": {"text": "你好", "voice": "longxing_v3", "format": "mp3", "rate": 1.5},
    }
    assert seen["download"] == "https://cdn/a.mp3"


@pytest.mark.asyncio
async def test_synthesize_inline_base64(monkeypatch):
    """兼容流式风格的 output.audio.data 内联 base64（免二次 GET）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/SpeechSynthesizer")
        return httpx.Response(
            200, json={"output": {"audio": {"data": base64.b64encode(b"INLINE").decode()}}}
        )

    _install(monkeypatch, handler)
    assert await synthesize("你好", voice_id="longxing_v3", rate=1.0, conn=_CONN) == b"INLINE"


@pytest.mark.asyncio
async def test_synthesize_wraps_auth_and_server_errors(monkeypatch):
    """D-3 教训：任何云端错误必须包成 TTSEngineError，不击穿降级语义。"""

    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": "InvalidApiKey", "message": "Invalid API-key"})

    _install(monkeypatch, denied)
    with pytest.raises(TTSEngineError, match="API Key 无效"):
        await synthesize("你好", voice_id="longxing_v3", rate=1.0, conn=_CONN)

    def crashed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="<html>boom</html>")  # 非 JSON 错误体

    _install(monkeypatch, crashed)
    with pytest.raises(TTSEngineError, match="HTTP 500"):
        await synthesize("你好", voice_id="longxing_v3", rate=1.0, conn=_CONN)


@pytest.mark.asyncio
async def test_synthesize_rejects_empty_audio(monkeypatch):
    def no_url(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output": {}})

    _install(monkeypatch, no_url)
    with pytest.raises(TTSEngineError, match="未返回音频"):
        await synthesize("你好", voice_id="longxing_v3", rate=1.0, conn=_CONN)

    def empty_download(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/SpeechSynthesizer"):
            return httpx.Response(200, json={"output": {"audio": {"url": "https://cdn/x"}}})
        return httpx.Response(200, content=b"")

    _install(monkeypatch, empty_download)
    with pytest.raises(TTSEngineError, match="音频为空"):
        await synthesize("你好", voice_id="longxing_v3", rate=1.0, conn=_CONN)


@pytest.mark.asyncio
async def test_probe_ok_and_fail(monkeypatch):
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"output": {"audio": {"data": base64.b64encode(b"MP3").decode()}}}
        )

    _install(monkeypatch, ok)
    assert await probe(_CONN) == (True, "")

    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"code": "AccessDenied", "message": "no"})

    _install(monkeypatch, denied)
    ok_flag, hint = await probe(_CONN)
    assert ok_flag is False
    assert "API Key 无效" in hint


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "connection", "json", "shape", "base64"])
async def test_cloud_failures_use_readable_error_and_text_fallback(monkeypatch, failure):
    from mochi_server.tts import cache, engine

    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        if failure == "connection":
            raise httpx.ConnectError("offline", request=request)
        if failure == "json":
            return httpx.Response(200, text="<html>gateway error</html>")
        if failure == "shape":
            return httpx.Response(200, json=["unexpected"])
        return httpx.Response(200, json={"output": {"audio": {"data": "%%%invalid"}}})

    _install(monkeypatch, handler)
    with pytest.raises(TTSEngineError):
        await synthesize("audit", voice_id="longxing_v3", rate=1.0, conn=_CONN)
    ok, hint = await probe(_CONN)
    assert ok is False
    assert "CosyVoice 合成失败" in hint
    monkeypatch.setattr(cache, "CACHE", cache.TTSCache())
    audio, used, hit = await engine.synthesize(
        "audit", voice_id="longxing_v3", rate=1.0, conn=_CONN
    )
    assert (audio, used, hit) == (b"", "text-fallback", False)


def test_resolve_speech_connection_branches():
    store = KeyStore()
    config = AppConfig()

    # 未绑定 → None
    assert resolve_speech_connection(config, store) is None

    # 绑定但连接不存在 → None
    config.voice.connection_id = "ghost"
    assert resolve_speech_connection(config, store) is None

    # 连接存在但 Key 被删 → None
    store.set_key("bailian-voice", "sk-live")
    config.model.connections["bailian-voice"] = ModelConnectionConfig(
        preset_id="dashscope", display_name="百炼（语音）", endpoints={}
    )
    config.voice.connection_id = "bailian-voice"
    store.delete_key("bailian-voice")  # InMemoryKeyring 是全局后端：删 Key 模拟缺失
    assert resolve_speech_connection(config, store) is None

    # 正常：原生端点固定，连接只贡献 Key
    store.set_key("bailian-voice", "sk-live")
    conn = resolve_speech_connection(config, store)
    assert conn == SpeechConnection(connection_id="bailian-voice", api_key="sk-live")
