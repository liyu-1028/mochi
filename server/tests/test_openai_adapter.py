"""OpenAI 兼容适配器测试：流式、错误翻译、Ollama 特化。

mock 策略（ADR-0002 D1）：httpx.MockTransport 经 AsyncOpenAI(http_client=...) 注入，
覆盖 SDK 真实请求路径；不引入 respx。
"""

from __future__ import annotations

import json

import httpx
import pytest
from openai import AsyncOpenAI

from mochi_server.agent import AgentError, OpenAICompatibleAdapter
from mochi_server.config import ModelProviderConfig
from mochi_server.events import ErrorCode
from mochi_server.secrets import KeyStore

_BASE_URL = "https://api.example.com/v1"


# ---------------------------------------------------------------------------
# SSE 构造辅助
# ---------------------------------------------------------------------------


def _chunk(delta: str = "", finish: str | None = None, **extra) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": "test-model",
        "choices": [
            {"index": 0, "delta": {"content": delta} if delta else {}, "finish_reason": finish}
        ],
        **extra,
    }


def _sse(*chunks: dict) -> bytes:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks)
    return (body + "data: [DONE]\n\n").encode()


def _error_response(status: int, message: str) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"message": message, "type": "invalid_request_error"}},
        request=httpx.Request("POST", f"{_BASE_URL}/chat/completions"),
    )


def _streaming_response(chunks: dict | None = None, body: bytes | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        content=body if body is not None else _sse(*(chunks or [])),
        headers={"content-type": "text/event-stream"},
    )


def _make_adapter(
    handler,
    *,
    kind: str = "openai_compatible",
    model: str = "test-model",
    base_url: str = _BASE_URL,
) -> OpenAICompatibleAdapter:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncOpenAI(
        api_key="sk-test", base_url=base_url, http_client=http_client, max_retries=0
    )
    cfg = ModelProviderConfig(kind=kind, display_name="测试", base_url=base_url, model=model)  # type: ignore[arg-type]
    return OpenAICompatibleAdapter("test", cfg, KeyStore(), client=client)


async def _collect(adapter: OpenAICompatibleAdapter) -> list[str]:
    return [d async for d in adapter.stream_chat([{"role": "user", "content": "你好"}], run_id="r")]


# ---------------------------------------------------------------------------
# 流式正常路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_yields_deltas() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _streaming_response(
            body=_sse(_chunk("你好，"), _chunk("我是 Mochi"), _chunk(finish="stop"))
        )

    deltas = await _collect(_make_adapter(handler))
    assert deltas == ["你好，", "我是 Mochi"]


@pytest.mark.asyncio
async def test_stream_skips_empty_choices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        no_choices = {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "m",
            "choices": [],
        }
        return _streaming_response(body=_sse(no_choices, _chunk("有效内容")))

    assert await _collect(_make_adapter(handler)) == ["有效内容"]


# ---------------------------------------------------------------------------
# SDK 异常 → ErrorCode 翻译
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_401_maps_to_model_auth() -> None:
    adapter = _make_adapter(lambda r: _error_response(401, "Invalid API key"))
    with pytest.raises(AgentError) as exc_info:
        await _collect(adapter)
    assert exc_info.value.payload.code == ErrorCode.MODEL_AUTH
    assert exc_info.value.payload.retryable is False
    assert exc_info.value.payload.hint  # 有引导文案


@pytest.mark.asyncio
async def test_429_maps_to_rate_limit_retryable() -> None:
    adapter = _make_adapter(lambda r: _error_response(429, "Too many requests"))
    with pytest.raises(AgentError) as exc_info:
        await _collect(adapter)
    assert exc_info.value.payload.code == ErrorCode.MODEL_RATE_LIMIT
    assert exc_info.value.payload.retryable is True


@pytest.mark.asyncio
async def test_404_maps_to_model_unavailable() -> None:
    adapter = _make_adapter(
        lambda r: _error_response(404, "model 'ghost' not found"), model="ghost"
    )
    with pytest.raises(AgentError) as exc_info:
        await _collect(adapter)
    payload = exc_info.value.payload
    assert payload.code == ErrorCode.MODEL_UNAVAILABLE
    assert "ghost" in payload.message


@pytest.mark.asyncio
async def test_400_context_overflow_maps_to_context_overflow() -> None:
    adapter = _make_adapter(
        lambda r: _error_response(
            400, "This model's maximum context length is 4096 tokens. However, you requested 9999"
        )
    )
    with pytest.raises(AgentError) as exc_info:
        await _collect(adapter)
    assert exc_info.value.payload.code == ErrorCode.CONTEXT_OVERFLOW


@pytest.mark.asyncio
async def test_5xx_maps_to_unavailable_retryable() -> None:
    adapter = _make_adapter(lambda r: _error_response(503, "overloaded"))
    with pytest.raises(AgentError) as exc_info:
        await _collect(adapter)
    payload = exc_info.value.payload
    assert payload.code == ErrorCode.MODEL_UNAVAILABLE
    assert payload.retryable is True


@pytest.mark.asyncio
async def test_connection_error_maps_to_network() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(AgentError) as exc_info:
        await _collect(_make_adapter(handler))
    assert exc_info.value.payload.code == ErrorCode.NETWORK
    assert exc_info.value.payload.retryable is True


@pytest.mark.asyncio
async def test_timeout_maps_to_network() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(AgentError) as exc_info:
        await _collect(_make_adapter(handler))
    assert exc_info.value.payload.code == ErrorCode.NETWORK


# ---------------------------------------------------------------------------
# Ollama 特化
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_chunk_error_field_detected() -> None:
    """Ollama 部分错误不走 HTTP 状态码，而是流内 chunk 的 error 字段。"""

    def handler(request: httpx.Request) -> httpx.Response:
        error_chunk = _chunk() | {"error": {"message": "context length exceeded"}}
        return _streaming_response(body=_sse(error_chunk))

    adapter = _make_adapter(handler, kind="ollama", base_url="http://127.0.0.1:11434")
    with pytest.raises(AgentError) as exc_info:
        await _collect(adapter)
    assert exc_info.value.payload.code == ErrorCode.CONTEXT_OVERFLOW


def test_ollama_v1_url_suffix_handling() -> None:
    from mochi_server.agent.adapters.openai_compat import _ollama_v1_url

    assert _ollama_v1_url(None) == "http://127.0.0.1:11434/v1"
    assert _ollama_v1_url("http://127.0.0.1:11434/") == "http://127.0.0.1:11434/v1"
    assert _ollama_v1_url("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1"
    assert _ollama_v1_url("http://localhost:11435") == "http://localhost:11435/v1"


# ---------------------------------------------------------------------------
# ping 连通性测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _streaming_response(body=_sse(_chunk("pong")))

    ok, reason = await _make_adapter(handler).ping()
    assert ok is True
    assert reason == "连接成功"


@pytest.mark.asyncio
async def test_ping_failure_returns_hint() -> None:
    adapter = _make_adapter(lambda r: _error_response(401, "bad key"))
    ok, reason = await adapter.ping()
    assert ok is False
    assert "API Key" in reason


# ---------------------------------------------------------------------------
# 构造期校验
# ---------------------------------------------------------------------------


def test_missing_key_raises_agent_error_for_cloud_provider() -> None:
    cfg = ModelProviderConfig(
        kind="openai_compatible", display_name="云端", base_url=_BASE_URL, model="m"
    )
    with pytest.raises(AgentError) as exc_info:
        OpenAICompatibleAdapter("no_key_provider", cfg, KeyStore())
    assert exc_info.value.payload.code == ErrorCode.MODEL_AUTH
    assert exc_info.value.payload.hint is not None


def test_ollama_needs_no_key() -> None:
    """Ollama 无 Key 也能构造（占位符 api_key）。"""
    cfg = ModelProviderConfig(
        kind="ollama", display_name="本地", base_url="http://127.0.0.1:11434", model="qwen3:8b"
    )
    adapter = OpenAICompatibleAdapter("ollama", cfg, KeyStore())
    assert adapter is not None
