"""LLMAgentService 测试：协议事件序列与异常上抛（fake adapter）。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from mochi_server.agent import AgentError, LLMAgentService, ProviderAdapter
from mochi_server.agent.adapters.base import ChatMessage
from mochi_server.agent.service import AgentContext
from mochi_server.events import ErrorCode, ErrorPayload

#: 裸字符串视为正文增量；元组可显式指定 ("thinking", ...) 推理流
DeltaItem = str | tuple[str, str]


class FakeAdapter(ProviderAdapter):
    """按预设增量序列产出；可注入中途异常。"""

    def __init__(self, deltas: list[DeltaItem], *, fail_after: int | None = None) -> None:
        self._deltas = deltas
        self._fail_after = fail_after
        self.last_messages: list[ChatMessage] | None = None

    async def stream_chat(
        self, messages: list[ChatMessage], *, run_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        self.last_messages = messages
        for i, item in enumerate(self._deltas):
            if self._fail_after is not None and i == self._fail_after:
                raise AgentError(
                    ErrorPayload(
                        code=ErrorCode.MODEL_RATE_LIMIT, message="请求太频繁了", retryable=True
                    )
                )
            yield ("text", item) if isinstance(item, str) else item

    async def ping(self) -> tuple[bool, str]:
        return True, "连接成功"


def _ctx() -> AgentContext:
    return AgentContext(run_id="r-1", session_id="s-1", text="你好呀")


async def _run(agent: LLMAgentService) -> list[tuple[str, object]]:
    return [(t, p) async for t, p in agent.run(_ctx())]


@pytest.mark.asyncio
async def test_event_sequence_matches_protocol() -> None:
    agent = LLMAgentService(FakeAdapter(["你好，", "我是 Mochi"]))
    events = await _run(agent)
    types = [t for t, _ in events]

    # 无推理流的提供方：thinking 骨架不带 delta（M1-S0 起不再硬编码占位）
    assert types == [
        "state.change",  # thinking
        "thinking.start",
        "thinking.end",
        "state.change",  # talking
        "emotion",
        "text.start",
        "text.delta",
        "text.delta",
        "text.end",
        "state.change",  # idle
    ]
    states = [p.state for t, p in events if t == "state.change"]
    assert states == ["thinking", "talking", "idle"]


@pytest.mark.asyncio
async def test_thinking_deltas_streamed_before_text() -> None:
    """M1-S0：适配层真实推理流（如 Anthropic thinking block）透传为 thinking.delta。"""
    agent = LLMAgentService(
        FakeAdapter([("thinking", "先分析，"), ("thinking", "再回答。"), "你好"])
    )
    events = await _run(agent)
    types = [t for t, _ in events]

    assert types == [
        "state.change",  # thinking
        "thinking.start",
        "thinking.delta",
        "thinking.delta",
        "thinking.end",
        "state.change",  # talking
        "emotion",
        "text.start",
        "text.delta",
        "text.end",
        "state.change",  # idle
    ]
    thinking = "".join(p.delta for t, p in events if t == "thinking.delta")
    assert thinking == "先分析，再回答。"
    assert [p.delta for t, p in events if t == "text.delta"] == ["你好"]
    end = next(p for t, p in events if t == "text.end")
    assert end.full_text == "你好"  # thinking 内容不并入正文


@pytest.mark.asyncio
async def test_thinking_only_response_keeps_sequence_complete() -> None:
    """纯 thinking 无正文：骨架仍完整，text.end.full_text 为空。"""
    agent = LLMAgentService(FakeAdapter([("thinking", "想岔了")]))
    events = await _run(agent)
    types = [t for t, _ in events]
    assert types[-3:] == ["text.start", "text.end", "state.change"]
    end = next(p for t, p in events if t == "text.end")
    assert end.full_text == ""


@pytest.mark.asyncio
async def test_emotion_is_neutral_in_m0() -> None:
    """ADR-0002 D5：真实模型固定 neutral/0.5，情绪推断推迟 M1。"""
    agent = LLMAgentService(FakeAdapter(["嗨"]))
    events = await _run(agent)
    emotion = next(p for t, p in events if t == "emotion")
    assert emotion.emotion == "neutral"
    assert emotion.intensity == 0.5


@pytest.mark.asyncio
async def test_text_deltas_concat_to_full_text() -> None:
    agent = LLMAgentService(FakeAdapter(["第一", "段", "第二段"]))
    events = await _run(agent)
    deltas = [p.delta for t, p in events if t == "text.delta"]
    end = next(p for t, p in events if t == "text.end")
    assert "".join(deltas) == end.full_text == "第一段第二段"


@pytest.mark.asyncio
async def test_empty_response_still_emits_start_end() -> None:
    agent = LLMAgentService(FakeAdapter([]))
    events = await _run(agent)
    types = [t for t, _ in events]
    assert "text.start" in types and "text.end" in types
    end = next(p for t, p in events if t == "text.end")
    assert end.full_text == ""


@pytest.mark.asyncio
async def test_adapter_error_propagates_to_run_manager() -> None:
    agent = LLMAgentService(FakeAdapter(["开头", "第二段"], fail_after=1))
    with pytest.raises(AgentError) as exc_info:
        await _run(agent)
    assert exc_info.value.payload.code == ErrorCode.MODEL_RATE_LIMIT


@pytest.mark.asyncio
async def test_system_prompt_and_user_text_forwarded() -> None:
    adapter = FakeAdapter(["回复"])
    agent = LLMAgentService(adapter, system_prompt="自定义人设")
    await _run(agent)
    assert adapter.last_messages is not None
    assert adapter.last_messages[0] == {"role": "system", "content": "自定义人设"}
    assert adapter.last_messages[1] == {"role": "user", "content": "你好呀"}
