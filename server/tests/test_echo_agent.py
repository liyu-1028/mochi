"""EchoAgentService 事件序列测试（桩模型契约）。"""

from __future__ import annotations

import pytest

from mochi_server.agent import AgentContext, EchoAgentService
from mochi_server.events import TextDeltaData, TextEndData


def _ctx() -> AgentContext:
    return AgentContext(run_id="r-test", session_id="s-test", text="你好，Mochi")


async def _collect(agent: EchoAgentService) -> list[tuple[str, object]]:
    return [(t, d) async for t, d in agent.run(_ctx())]


@pytest.mark.asyncio
async def test_event_sequence_shape() -> None:
    """序列骨架：thinking 开场、talking 收尾、state.change 贯穿。"""
    events = await _collect(EchoAgentService(chunk_delay=0, thinking_delay=0))
    types = [t for t, _ in events]

    assert types[0] == "state.change"
    assert events[0][1].state == "thinking"  # type: ignore[attr-defined]
    assert types[-1] == "state.change"
    assert events[-1][1].state == "idle"  # type: ignore[attr-defined]
    assert "thinking.start" in types
    assert "thinking.end" in types
    assert "text.start" in types
    assert "text.end" in types
    assert "emotion" in types
    # start/end 配对且顺序正确
    assert types.index("thinking.start") < types.index("thinking.end")
    assert types.index("text.start") < types.index("text.end")


@pytest.mark.asyncio
async def test_text_deltas_concat_to_full_text() -> None:
    """流式完整性：delta 拼接 == fullText（协议 §5.3）。"""
    events = await _collect(EchoAgentService(chunk_delay=0, thinking_delay=0))
    delta_payloads = [d for t, d in events if t == "text.delta"]
    ends = [d for t, d in events if t == "text.end"]

    assert isinstance(ends[0], TextEndData)
    assert delta_payloads, "至少应有一个 text.delta"
    assert all(isinstance(d, TextDeltaData) for d in delta_payloads)
    assert "".join(d.delta for d in delta_payloads) == ends[0].full_text


@pytest.mark.asyncio
async def test_echo_contains_user_input() -> None:
    """回显语义：回复中包含用户输入。"""
    events = await _collect(EchoAgentService(chunk_delay=0, thinking_delay=0))
    full = next(d.full_text for t, d in events if t == "text.end")
    assert _ctx().text in full
