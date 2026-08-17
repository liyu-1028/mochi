"""LangChain 适配器测试（M1-S4，ADR-0008 D2）：工厂、流式分拣、空流守卫、错误翻译。

mock 策略（沿 ADR-0002 D1「不引入 respx」精神，按路径分化，见 ADR-0008 D2）：
- openai/ollama 路径：httpx.MockTransport 经 ChatOpenAI(http_async_client=...)
  注入，覆盖 SDK 真实请求路径（该路径有 client 注入缝）；
- anthropic 路径：LC 1.5 无 client 注入缝（未知 kwarg 被转 model_kwargs 打到
  create() 上，实测 2026-08-17），错误表直接构造 SDK 异常单测，流式分拣经
  ScriptedModel 注入验证；真实 thinking 流已由 spike 验证（ADR-0008 附注）。
"""

from __future__ import annotations

import json
from typing import Any

import anthropic as anthropic_sdk
import httpx
import keyring
import openai as openai_sdk
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from pydantic import Field

from mochi_server.agent import AgentError, LangChainAdapter
from mochi_server.agent.adapters.langchain import (
    _ollama_v1_url,
    _to_lc_messages,
    _translate_sdk_error,
)
from mochi_server.config import ModelProviderConfig
from mochi_server.events import ErrorCode
from mochi_server.secrets import InMemoryKeyring, KeyStore

_BASE_URL = "https://api.example.com/v1"


def _cfg(kind: str, *, model: str = "test-model", base_url: str | None = _BASE_URL):
    return ModelProviderConfig(
        kind=kind,  # type: ignore[arg-type]
        display_name="测试",
        base_url=base_url,
        model=model,
    )


def _mem_key_store(provider_id: str = "test", key: str = "sk-test") -> KeyStore:
    """进程内钥匙串（隔离真实钥匙串，secrets.py 测试基建）。"""
    keyring.set_keyring(InMemoryKeyring())
    store = KeyStore()
    store.set_key(provider_id, key)
    return store


# ---------------------------------------------------------------------------
# 剧本假模型：按 script 吐 chunk / 抛异常，记录收到的消息（测试注入缝消费方）
# ---------------------------------------------------------------------------


class ScriptedModel(BaseChatModel):
    script: list[Any] = Field(default_factory=list)
    received: list[list[Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.received.append(list(messages))
        for item in self.script:  # 剧本里的 Exception 在任意调用路径（含 ping 的 ainvoke）都抛出
            if isinstance(item, Exception):
                raise item
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="pong"))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        self.received.append(list(messages))
        for item in self.script:  # 剧本里的 Exception 实例直接抛出
            if isinstance(item, Exception):
                raise item
            # LC 契约：_astream 须 yield ChatGenerationChunk（.message 为增量）
            yield ChatGenerationChunk(message=item)


def _scripted_adapter(script: list[Any], *, kind: str = "anthropic") -> LangChainAdapter:
    model = ScriptedModel(script=script)
    return LangChainAdapter("test", _cfg(kind), _mem_key_store(), model=model)


async def _collect(adapter: LangChainAdapter) -> list[tuple[str, str]]:
    return [d async for d in adapter.stream_chat([{"role": "user", "content": "你好"}], run_id="r")]


# ---------------------------------------------------------------------------
# 构造与工厂
# ---------------------------------------------------------------------------


def test_missing_key_raises_agent_error_for_openai_compatible() -> None:
    with pytest.raises(AgentError) as exc_info:
        LangChainAdapter("no_key", _cfg("openai_compatible"), KeyStore())
    assert exc_info.value.payload.code == ErrorCode.MODEL_AUTH
    assert exc_info.value.payload.hint is not None


def test_missing_key_raises_agent_error_for_anthropic() -> None:
    with pytest.raises(AgentError) as exc_info:
        LangChainAdapter("no_key", _cfg("anthropic"), KeyStore())
    assert exc_info.value.payload.code == ErrorCode.MODEL_AUTH


def test_ollama_needs_no_key() -> None:
    """Ollama 无 Key 也能构造（占位符 api_key，沿旧适配器行为）。"""
    keyring.set_keyring(InMemoryKeyring())
    adapter = LangChainAdapter("ollama", _cfg("ollama"), KeyStore())
    assert isinstance(adapter.chat_model, ChatOpenAI)


def test_anthropic_builds_chat_anthropic_with_key() -> None:
    adapter = LangChainAdapter("test", _cfg("anthropic"), _mem_key_store())
    assert isinstance(adapter.chat_model, BaseChatModel)


def test_ollama_v1_url_suffix_handling() -> None:
    assert _ollama_v1_url(None) == "http://127.0.0.1:11434/v1"
    assert _ollama_v1_url("http://127.0.0.1:11434/") == "http://127.0.0.1:11434/v1"
    assert _ollama_v1_url("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1"
    assert _ollama_v1_url("http://localhost:11435") == "http://localhost:11435/v1"


# ---------------------------------------------------------------------------
# 流式分拣与消息转换（ScriptedModel 注入）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_yields_text_deltas() -> None:
    adapter = _scripted_adapter([AIMessageChunk(content="你好，"), AIMessageChunk(content="Mochi")])
    assert await _collect(adapter) == [("text", "你好，"), ("text", "Mochi")]


@pytest.mark.asyncio
async def test_stream_yields_thinking_then_text() -> None:
    """anthropic 流式 content 块分拣；thinking 文本在线上格式的 ``thinking`` 键。"""
    adapter = _scripted_adapter(
        [
            AIMessageChunk(content=[{"type": "thinking", "thinking": "先想一下", "index": 0}]),
            AIMessageChunk(content=[{"type": "text", "text": "答案是 42"}]),
        ]
    )
    assert await _collect(adapter) == [("thinking", "先想一下"), ("text", "答案是 42")]


@pytest.mark.asyncio
async def test_stream_empty_triggers_guard() -> None:
    """空流守卫：零增量兜底（补偿 Ollama 流内 error 字段经 LC 归一化丢失）。"""
    adapter = _scripted_adapter([AIMessageChunk(content="")], kind="ollama")
    with pytest.raises(AgentError) as exc_info:
        await _collect(adapter)
    payload = exc_info.value.payload
    assert payload.code == ErrorCode.MODEL_UNAVAILABLE
    assert payload.retryable is True
    assert "ollama pull" in payload.hint


@pytest.mark.asyncio
async def test_anthropic_path_merges_consecutive_same_role() -> None:
    """Anthropic 要求角色交替：连续同角色消息合并（移植旧 _split_system 行为）。"""
    model = ScriptedModel(script=[AIMessageChunk(content="好")])
    adapter = LangChainAdapter("test", _cfg("anthropic"), _mem_key_store(), model=model)
    msgs = [
        {"role": "system", "content": "系统"},
        {"role": "user", "content": "第一问"},
        {"role": "user", "content": "第二问"},
    ]
    async for _ in adapter.stream_chat(msgs, run_id="r"):
        pass
    assert model.received[0] == [
        SystemMessage(content="系统"),
        HumanMessage(content="第一问\n第二问"),
    ]


def test_to_lc_messages_merges_for_anthropic() -> None:
    messages = [
        {"role": "system", "content": "系统A"},
        {"role": "user", "content": "第一问"},
        {"role": "user", "content": "第二问"},
        {"role": "assistant", "content": "答"},
    ]
    out = _to_lc_messages(messages, anthropic_style=True)
    assert out == [
        SystemMessage(content="系统A"),
        HumanMessage(content="第一问\n第二问"),
        AIMessage(content="答"),
    ]


def test_to_lc_messages_keeps_consecutive_for_openai() -> None:
    messages = [
        {"role": "user", "content": "第一问"},
        {"role": "user", "content": "第二问"},
    ]
    out = _to_lc_messages(messages, anthropic_style=False)
    assert out == [HumanMessage(content="第一问"), HumanMessage(content="第二问")]


# ---------------------------------------------------------------------------
# ping 连通性
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_success() -> None:
    ok, reason = await _scripted_adapter([AIMessageChunk(content="pong")]).ping()
    assert ok is True
    assert reason == "连接成功"


@pytest.mark.asyncio
async def test_ping_failure_returns_hint() -> None:
    adapter = _scripted_adapter(
        [_openai_error(openai_sdk.AuthenticationError, 401, "Invalid API key")]
    )
    ok, reason = await adapter.ping()
    assert ok is False
    assert "API Key" in reason


# ---------------------------------------------------------------------------
# SDK 异常 → ErrorCode 翻译（直接构造两族异常，语义与旧适配器逐条对齐）
# ---------------------------------------------------------------------------

_OPENAI_REQ = httpx.Request("POST", f"{_BASE_URL}/chat/completions")
_ANTHROPIC_REQ = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _openai_error(cls, status: int, message: str) -> Exception:
    # stainless 两族构造签名一致：(message, *, response, body)
    body = {"error": {"message": message, "type": "invalid_request_error"}}
    return cls(message, response=httpx.Response(status, json=body, request=_OPENAI_REQ), body=body)


def _anthropic_error(cls, status: int, message: str) -> Exception:
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    return cls(
        message, response=httpx.Response(status, json=body, request=_ANTHROPIC_REQ), body=body
    )


@pytest.mark.parametrize(
    ("family", "cls"),
    [("openai", openai_sdk.AuthenticationError), ("anthropic", anthropic_sdk.AuthenticationError)],
)
def test_401_maps_to_model_auth(family, cls) -> None:
    make = _openai_error if family == "openai" else _anthropic_error
    err = _translate_sdk_error(make(cls, 401, "bad key"), model="m")
    assert err.payload.code == ErrorCode.MODEL_AUTH
    assert err.payload.retryable is False
    assert err.payload.hint


@pytest.mark.parametrize(
    ("family", "cls"),
    [
        ("openai", openai_sdk.PermissionDeniedError),
        ("anthropic", anthropic_sdk.PermissionDeniedError),
    ],
)
def test_403_maps_to_model_auth_no_access(family, cls) -> None:
    make = _openai_error if family == "openai" else _anthropic_error
    err = _translate_sdk_error(make(cls, 403, "no access"), model="m")
    assert err.payload.code == ErrorCode.MODEL_AUTH
    assert "无权" in err.payload.message


@pytest.mark.parametrize(
    ("family", "cls"),
    [("openai", openai_sdk.NotFoundError), ("anthropic", anthropic_sdk.NotFoundError)],
)
def test_404_maps_to_model_unavailable(family, cls) -> None:
    make = _openai_error if family == "openai" else _anthropic_error
    err = _translate_sdk_error(make(cls, 404, "model not found"), model="ghost")
    payload = err.payload
    assert payload.code == ErrorCode.MODEL_UNAVAILABLE
    assert "ghost" in payload.message
    # OpenAI 系还承载 Ollama /v1：404 hint 附 pull 引导；anthropic 族不附
    if family == "openai":
        assert "ollama pull" in payload.hint
    else:
        assert "ollama pull" not in payload.hint


@pytest.mark.parametrize(
    ("family", "cls"),
    [("openai", openai_sdk.RateLimitError), ("anthropic", anthropic_sdk.RateLimitError)],
)
def test_429_maps_to_rate_limit_retryable(family, cls) -> None:
    make = _openai_error if family == "openai" else _anthropic_error
    err = _translate_sdk_error(make(cls, 429, "slow down"), model="m")
    assert err.payload.code == ErrorCode.MODEL_RATE_LIMIT
    assert err.payload.retryable is True


@pytest.mark.parametrize(
    ("family", "cls"),
    [("openai", openai_sdk.APIStatusError), ("anthropic", anthropic_sdk.APIStatusError)],
)
def test_402_maps_to_quota(family, cls) -> None:
    """MiniMax 等兼容端点以 402 表示余额不足（实测 2026-08-05）。"""
    make = _openai_error if family == "openai" else _anthropic_error
    err = _translate_sdk_error(make(cls, 402, "insufficient balance"), model="m")
    assert err.payload.code == ErrorCode.MODEL_QUOTA
    assert err.payload.retryable is False


@pytest.mark.parametrize(
    ("family", "cls"),
    [("openai", openai_sdk.APITimeoutError), ("anthropic", anthropic_sdk.APITimeoutError)],
)
def test_timeout_maps_to_network(family, cls) -> None:
    request = _OPENAI_REQ if family == "openai" else _ANTHROPIC_REQ
    exc = cls(request=request)
    err = _translate_sdk_error(exc, model="m")
    assert err.payload.code == ErrorCode.NETWORK
    assert err.payload.retryable is True


@pytest.mark.parametrize(
    ("family", "cls"),
    [("openai", openai_sdk.APIConnectionError), ("anthropic", anthropic_sdk.APIConnectionError)],
)
def test_connection_error_maps_to_network(family, cls) -> None:
    request = _OPENAI_REQ if family == "openai" else _ANTHROPIC_REQ
    err = _translate_sdk_error(cls(request=request), model="m")
    assert err.payload.code == ErrorCode.NETWORK


@pytest.mark.parametrize(
    ("family", "cls"),
    [("openai", openai_sdk.BadRequestError), ("anthropic", anthropic_sdk.BadRequestError)],
)
def test_400_overflow_maps_to_context_overflow(family, cls) -> None:
    make = _openai_error if family == "openai" else _anthropic_error
    err = _translate_sdk_error(
        make(cls, 400, "prompt is too long: maximum context length is 4096"), model="m"
    )
    assert err.payload.code == ErrorCode.CONTEXT_OVERFLOW
    assert err.payload.retryable is False


@pytest.mark.parametrize(
    ("family", "cls"),
    [("openai", openai_sdk.BadRequestError), ("anthropic", anthropic_sdk.BadRequestError)],
)
def test_400_other_maps_to_internal(family, cls) -> None:
    make = _openai_error if family == "openai" else _anthropic_error
    err = _translate_sdk_error(make(cls, 400, "bad request"), model="m")
    assert err.payload.code == ErrorCode.INTERNAL


@pytest.mark.parametrize(
    ("family", "cls"),
    [("openai", openai_sdk.InternalServerError), ("anthropic", anthropic_sdk.InternalServerError)],
)
def test_5xx_maps_to_unavailable_retryable(family, cls) -> None:
    make = _openai_error if family == "openai" else _anthropic_error
    err = _translate_sdk_error(make(cls, 503, "overloaded"), model="m")
    assert err.payload.code == ErrorCode.MODEL_UNAVAILABLE
    assert err.payload.retryable is True


def test_unknown_error_falls_back_to_internal() -> None:
    err = _translate_sdk_error(ValueError("boom"), model="m")
    assert err.payload.code == ErrorCode.INTERNAL
    assert err.payload.retryable is True


# ---------------------------------------------------------------------------
# wire 级（openai 路径）：httpx.MockTransport 经 ChatOpenAI(http_async_client=...)
# ---------------------------------------------------------------------------


def _chunk(delta: str = "", finish: str | None = None) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": "test-model",
        "choices": [
            {"index": 0, "delta": {"content": delta} if delta else {}, "finish_reason": finish}
        ],
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


def _wire_adapter(handler, *, kind: str = "openai_compatible", model: str = "test-model"):
    chat = ChatOpenAI(
        model=model,
        api_key="sk-test",
        base_url=_BASE_URL,
        timeout=60,
        max_retries=0,
        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return LangChainAdapter("test", _cfg(kind, model=model), _mem_key_store(), model=chat)


@pytest.mark.asyncio
async def test_wire_stream_yields_deltas() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _streaming_response(
            body=_sse(_chunk("你好，"), _chunk("我是 Mochi"), _chunk(finish="stop"))
        )

    assert await _collect(_wire_adapter(handler)) == [("text", "你好，"), ("text", "我是 Mochi")]


@pytest.mark.asyncio
async def test_wire_401_translates_to_model_auth() -> None:
    adapter = _wire_adapter(lambda r: _error_response(401, "Invalid API key"))
    with pytest.raises(AgentError) as exc_info:
        await _collect(adapter)
    assert exc_info.value.payload.code == ErrorCode.MODEL_AUTH


@pytest.mark.asyncio
async def test_wire_connection_error_maps_to_network() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(AgentError) as exc_info:
        await _collect(_wire_adapter(handler))
    assert exc_info.value.payload.code == ErrorCode.NETWORK


@pytest.mark.asyncio
async def test_wire_ollama_stream_error_sniffed_as_overflow() -> None:
    """Ollama 流内 error 字段经 LC 以异常抛出，消息含关键词 → 兜底嗅探译为溢出。

    （旧 _chunk_error_text 语义经此路径保留；纯空流才落到空流守卫。）
    """

    def handler(request: httpx.Request) -> httpx.Response:
        no_choices = {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "m",
            "choices": [],
            "error": {"message": "context length exceeded"},
        }
        return _streaming_response(body=_sse(no_choices))

    with pytest.raises(AgentError) as exc_info:
        await _collect(_wire_adapter(handler, kind="ollama"))
    assert exc_info.value.payload.code == ErrorCode.CONTEXT_OVERFLOW
