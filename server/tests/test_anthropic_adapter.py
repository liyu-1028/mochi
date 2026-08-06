"""Anthropic 适配器测试（M1-S0，ADR-0002 D1）：流式、thinking 流、错误翻译。

mock 策略沿用 ADR-0002 D1：httpx.MockTransport 经 AsyncAnthropic(http_client=...)
注入，覆盖 SDK 真实请求路径；不引入 respx。
"""

from __future__ import annotations

import json

import httpx
import pytest
from anthropic import AsyncAnthropic

from mochi_server.agent import AgentError, AnthropicAdapter
from mochi_server.config import ModelProviderConfig
from mochi_server.events import ErrorCode
from mochi_server.secrets import KeyStore


def _sse(*events: dict) -> bytes:
    out = ""
    for ev in events:
        out += f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n"
    return out.encode()


def _message_start() -> dict:
    return {
        "type": "message_start",
        "message": {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": "claude-sonnet-4",
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 1},
        },
    }


def _text_block(*texts: str) -> list[dict]:
    events: list[dict] = [
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
    ]
    for text in texts:
        events.append(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text},
            }
        )
    events.append({"type": "content_block_stop", "index": 0})
    return events


def _thinking_block(*texts: str) -> list[dict]:
    events: list[dict] = [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": ""},
        }
    ]
    for text in texts:
        events.append(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": text},
            }
        )
    events.append({"type": "content_block_stop", "index": 0})
    return events


def _message_end() -> list[dict]:
    return [
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    ]


def _streaming_response(*events: dict) -> httpx.Response:
    return httpx.Response(200, content=_sse(*events), headers={"content-type": "text/event-stream"})


def _error_response(status: int, error_type: str, message: str) -> httpx.Response:
    return httpx.Response(
        status,
        json={"type": "error", "error": {"type": error_type, "message": message}},
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )


def _make_adapter(handler, *, model: str = "claude-sonnet-4") -> AnthropicAdapter:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncAnthropic(api_key="sk-ant-test", http_client=http_client, max_retries=0)
    cfg = ModelProviderConfig(kind="anthropic", display_name="Claude", model=model)
    return AnthropicAdapter("claude", cfg, KeyStore(), client=client)


_MESSAGES = [{"role": "user", "content": "你好"}]


async def _collect(adapter: AnthropicAdapter) -> list[tuple[str, str]]:
    return [item async for item in adapter.stream_chat(_MESSAGES, run_id="r")]


# ---------------------------------------------------------------------------
# 流式正常路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_yields_text_deltas() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _streaming_response(
            _message_start(), *_text_block("你好，", "我是 Mochi"), *_message_end()
        )

    assert await _collect(_make_adapter(handler)) == [
        ("text", "你好，"),
        ("text", "我是 Mochi"),
    ]


@pytest.mark.asyncio
async def test_stream_yields_thinking_then_text() -> None:
    """thinking block → ("thinking", ...)；text block → ("text", ...)。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return _streaming_response(
            _message_start(),
            *_thinking_block("先分析，", "再回答。"),
            *_text_block("答案是 42"),
            *_message_end(),
        )

    assert await _collect(_make_adapter(handler)) == [
        ("thinking", "先分析，"),
        ("thinking", "再回答。"),
        ("text", "答案是 42"),
    ]


@pytest.mark.asyncio
async def test_non_delta_events_ignored() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _streaming_response(
            _message_start(),
            {"type": "ping"},
            *_text_block("有效内容"),
            *_message_end(),
        )

    assert await _collect(_make_adapter(handler)) == [("text", "有效内容")]


# ---------------------------------------------------------------------------
# 消息形态转换
# ---------------------------------------------------------------------------


def test_split_system_extracts_and_merges() -> None:
    from mochi_server.agent.adapters.anthropic import _split_system

    system, chat = _split_system(
        [
            {"role": "system", "content": "人设 A"},
            {"role": "system", "content": "人设 B"},
            {"role": "user", "content": "第一句"},
            {"role": "user", "content": "第二句"},  # 连续同角色 → 合并
            {"role": "assistant", "content": "回复"},
            {"role": "user", "content": "当前"},
        ]
    )
    assert system == "人设 A\n\n人设 B"
    assert chat == [
        {"role": "user", "content": "第一句\n第二句"},
        {"role": "assistant", "content": "回复"},
        {"role": "user", "content": "当前"},
    ]


@pytest.mark.asyncio
async def test_system_prompt_sent_as_top_level_param() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _streaming_response(_message_start(), *_text_block("ok"), *_message_end())

    adapter = _make_adapter(handler)
    messages = [
        {"role": "system", "content": "你是 Mochi"},
        {"role": "user", "content": "你好"},
    ]
    async for _ in adapter.stream_chat(messages, run_id="r"):
        pass
    assert captured["system"] == "你是 Mochi"
    assert captured["messages"] == [{"role": "user", "content": "你好"}]
    assert all(m["role"] != "system" for m in captured["messages"])


# ---------------------------------------------------------------------------
# SDK 异常 → ErrorCode 翻译
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_401_maps_to_model_auth() -> None:
    adapter = _make_adapter(
        lambda r: _error_response(401, "authentication_error", "invalid x-api-key")
    )
    with pytest.raises(AgentError) as exc_info:
        await _collect(adapter)
    assert exc_info.value.payload.code == ErrorCode.MODEL_AUTH
    assert exc_info.value.payload.retryable is False
    assert exc_info.value.payload.hint


@pytest.mark.asyncio
async def test_429_maps_to_rate_limit_retryable() -> None:
    adapter = _make_adapter(lambda r: _error_response(429, "rate_limit_error", "Too many requests"))
    with pytest.raises(AgentError) as exc_info:
        await _collect(adapter)
    assert exc_info.value.payload.code == ErrorCode.MODEL_RATE_LIMIT
    assert exc_info.value.payload.retryable is True


@pytest.mark.asyncio
async def test_402_maps_to_quota() -> None:
    """兼容端点（如 MiniMax）以 402 表示余额不足 → ERR_MODEL_QUOTA，不再落兜底。"""
    adapter = _make_adapter(
        lambda r: _error_response(402, "insufficient_balance_error", "insufficient balance (1008)")
    )
    with pytest.raises(AgentError) as exc_info:
        await _collect(adapter)
    payload = exc_info.value.payload
    assert payload.code == ErrorCode.MODEL_QUOTA
    assert payload.retryable is False
    assert "余额" in payload.message


@pytest.mark.asyncio
async def test_404_maps_to_model_unavailable() -> None:
    adapter = _make_adapter(
        lambda r: _error_response(404, "not_found_error", "model not found"), model="ghost"
    )
    with pytest.raises(AgentError) as exc_info:
        await _collect(adapter)
    payload = exc_info.value.payload
    assert payload.code == ErrorCode.MODEL_UNAVAILABLE
    assert "ghost" in payload.message


@pytest.mark.asyncio
async def test_400_context_overflow_maps_to_context_overflow() -> None:
    adapter = _make_adapter(
        lambda r: _error_response(400, "invalid_request_error", "prompt is too long: 999999 tokens")
    )
    with pytest.raises(AgentError) as exc_info:
        await _collect(adapter)
    assert exc_info.value.payload.code == ErrorCode.CONTEXT_OVERFLOW


@pytest.mark.asyncio
async def test_5xx_maps_to_unavailable_retryable() -> None:
    adapter = _make_adapter(lambda r: _error_response(529, "api_error", "overloaded"))
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
# ping 连通性测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _streaming_response(_message_start(), *_text_block("pong"), *_message_end())

    ok, reason = await _make_adapter(handler).ping()
    assert ok is True
    assert reason == "连接成功"


@pytest.mark.asyncio
async def test_ping_failure_returns_hint() -> None:
    adapter = _make_adapter(
        lambda r: _error_response(401, "authentication_error", "invalid x-api-key")
    )
    ok, reason = await adapter.ping()
    assert ok is False
    assert "API Key" in reason


# ---------------------------------------------------------------------------
# 构造期校验
# ---------------------------------------------------------------------------


def test_missing_key_raises_agent_error() -> None:
    cfg = ModelProviderConfig(kind="anthropic", display_name="Claude", model="claude-sonnet-4")
    with pytest.raises(AgentError) as exc_info:
        AnthropicAdapter("no_key_provider", cfg, KeyStore())
    assert exc_info.value.payload.code == ErrorCode.MODEL_AUTH
    assert exc_info.value.payload.hint is not None
