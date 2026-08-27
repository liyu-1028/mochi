"""情绪推断测试（M1-S4 后半，功能清单 2.5，ADR-0009）：分类器、降级链、补发管线。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fakes import ScriptedChatModel, make_test_adapter
from langchain_core.messages import AIMessageChunk

from mochi_server.agent import LLMAgentService, RunManager
from mochi_server.agent.emotion import classify_reply_emotion, parse_emotion_label
from mochi_server.agent.service import AgentContext
from mochi_server.events import Emotion

# ---------------------------------------------------------------------------
# 标签解析
# ---------------------------------------------------------------------------


def test_parse_exact_label() -> None:
    assert parse_emotion_label("happy") is Emotion.HAPPY
    assert parse_emotion_label("  sad\n") is Emotion.SAD


def test_parse_tolerates_junk() -> None:
    assert parse_emotion_label("**happy**") is Emotion.HAPPY
    assert parse_emotion_label("情绪：confused。") is Emotion.CONFUSED
    assert parse_emotion_label("我认为是 surprised") is Emotion.SURPRISED


def test_parse_unknown_returns_none() -> None:
    assert parse_emotion_label("excited") is None
    assert parse_emotion_label("") is None
    assert parse_emotion_label("无法判断") is None


# ---------------------------------------------------------------------------
# 分类调用（假适配器）
# ---------------------------------------------------------------------------


class _ScriptedClassifier:
    """按序回放文本增量的假 stream_chat。"""

    def __init__(self, chunks: list[str], *, delay: float = 0.0) -> None:
        self._chunks = chunks
        self._delay = delay
        self.calls: list[list[dict[str, str]]] = []

    async def stream_chat(self, messages: list[dict[str, str]], run_id: str = ""):
        self.calls.append(messages)
        for chunk in self._chunks:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield "text", chunk


@pytest.mark.asyncio
async def test_classify_success() -> None:
    classifier = _ScriptedClassifier(["em", "barrassed"])
    emotion = await classify_reply_emotion(classifier, "哎呀，被你发现了…")
    assert emotion is Emotion.EMBARRASSED
    # 调用形态：system 分类指令 + user 回复文本
    system, user = classifier.calls[0]
    assert "情绪分类器" in system["content"]
    assert "被你发现了" in user["content"]


@pytest.mark.asyncio
async def test_classify_timeout_returns_none() -> None:
    classifier = _ScriptedClassifier(["hap", "py"], delay=5.0)
    assert await classify_reply_emotion(classifier, "太开心了") is None


@pytest.mark.asyncio
async def test_classify_adapter_error_returns_none() -> None:
    class _Boom:
        async def stream_chat(self, messages, run_id=""):
            raise RuntimeError("网络炸了")
            yield  # pragma: no cover

    assert await classify_reply_emotion(_Boom(), "文本") is None


@pytest.mark.asyncio
async def test_classify_empty_text_short_circuits() -> None:
    classifier = _ScriptedClassifier(["happy"])
    assert await classify_reply_emotion(classifier, "   ") is None
    assert classifier.calls == []  # 空回复不发调用


# ---------------------------------------------------------------------------
# post_run_events（LLMAgentService 集成）
# ---------------------------------------------------------------------------


def _agent(calls: list[list[Any]], *, emotion_enabled: bool = True) -> LLMAgentService:
    return LLMAgentService(
        make_test_adapter(ScriptedChatModel(calls=calls)),
        emotion_enabled=emotion_enabled,
    )


def _ctx() -> AgentContext:
    return AgentContext(run_id="r-emotion", session_id="s", text="夸夸我")


@pytest.mark.asyncio
async def test_post_run_emits_classified_emotion() -> None:
    agent = _agent([[AIMessageChunk(content="哇，你太棒啦！")]])

    captured_reply: list[str] = []

    async def _fake_classify(adapter, reply):
        captured_reply.append(reply)
        return Emotion.HAPPY

    import mochi_server.agent.llm_agent as mod

    original = mod.classify_reply_emotion
    mod.classify_reply_emotion = _fake_classify
    try:
        _ = [e async for e in agent.run(_ctx())]
        events = await agent.post_run_events(_ctx())
    finally:
        mod.classify_reply_emotion = original

    assert captured_reply == ["哇，你太棒啦！"]
    assert len(events) == 1
    event_type, payload = events[0]
    assert event_type == "emotion"
    assert payload.emotion is Emotion.HAPPY
    assert payload.intensity == 0.75
    assert payload.run_id == "r-emotion"


@pytest.mark.asyncio
async def test_post_run_neutral_or_failure_no_event() -> None:
    agent = _agent([[AIMessageChunk(content="好的。")]])
    _ = [e async for e in agent.run(_ctx())]

    import mochi_server.agent.llm_agent as mod

    original = mod.classify_reply_emotion

    async def _none(adapter, reply):
        return None

    mod.classify_reply_emotion = _none
    try:
        assert await agent.post_run_events(_ctx()) == []
    finally:
        mod.classify_reply_emotion = original


@pytest.mark.asyncio
async def test_post_run_disabled_no_event() -> None:
    agent = _agent([[AIMessageChunk(content="好")]], emotion_enabled=False)
    _ = [e async for e in agent.run(_ctx())]
    assert await agent.post_run_events(_ctx()) == []


# ---------------------------------------------------------------------------
# RunManager 补发管线（run.finished 之后送达）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_manager_forwards_post_events_after_finished() -> None:
    agent = _agent([[AIMessageChunk(content="哼！")]])

    async def _fake_classify(adapter, reply):
        return Emotion.ANGRY

    import mochi_server.agent.llm_agent as mod

    original = mod.classify_reply_emotion
    mod.classify_reply_emotion = _fake_classify
    frames: list[tuple[str, Any]] = []

    async def send(frame: dict) -> None:
        frames.append((frame["type"], frame["data"]))

    try:
        manager = RunManager(lambda: agent, send)
        from types import SimpleNamespace

        await manager.start_run(SimpleNamespace(run_id="r-emotion", session_id="s", text="哼"))
        await manager._runs["r-emotion"]  # 等回合任务结束
    finally:
        mod.classify_reply_emotion = original

    types = [t for t, _ in frames]
    assert types[-1] == "emotion"  # run.finished 之后补发
    assert types[-2] == "run.finished"
    assert frames[-1][1]["emotion"] == Emotion.ANGRY  # data 是 dict（协议线上形态）
