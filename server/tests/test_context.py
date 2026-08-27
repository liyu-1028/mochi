"""上下文预算裁剪测试（M1-S4 后半，功能清单 4.4）。

覆盖：token 估算、预算计算、从新往旧裁剪、省略标记注入、巨消息尾部保留、
LLMAgentService 装配（小窗口下历史被裁且首轮输入仍完整）、缺省窗口零裁剪。
"""

from __future__ import annotations

from typing import Any

import pytest
from fakes import ScriptedChatModel, make_test_adapter
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.memory import InMemorySaver

from mochi_server.agent import LLMAgentService
from mochi_server.agent.context import (
    build_context_messages,
    compute_budget,
    estimate_messages_tokens,
    estimate_tokens,
    trim_history,
)
from mochi_server.agent.service import AgentContext

# ---------------------------------------------------------------------------
# token 估算
# ---------------------------------------------------------------------------


def test_estimate_tokens_cjk_vs_latin() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("你好世界") == 4  # CJK 1/字
    assert estimate_tokens("abcdefgh") == 2  # Latin 1/4 字符
    assert estimate_tokens("你好abc") == 2 + 1  # 混合


def test_estimate_tokens_cjk_punctuation_counts_full() -> None:
    # 全角标点（CJK 符号区）按 1 token 计
    assert estimate_tokens("，。！") == 3


def test_estimate_messages_tokens_adds_overhead() -> None:
    msgs = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你也好"},
    ]
    assert estimate_messages_tokens(msgs) == (2 + 8) + (3 + 8)


# ---------------------------------------------------------------------------
# 预算与裁剪
# ---------------------------------------------------------------------------


def test_compute_budget_formula() -> None:
    system, user = "系统提示七个字", "用户输入七个字"  # 各 7 CJK
    budget = compute_budget(system, user, context_window=1000)
    assert budget.context_window == 1000
    assert budget.reserved == (7 + 8) + (7 + 8)  # system + user 各加开销
    assert budget.margin == 250
    assert budget.available == 1000 - 30 - 250


def test_compute_budget_invalid_window_falls_back() -> None:
    assert compute_budget("s", "u", context_window=0).context_window == 8192
    assert compute_budget("s", "u", context_window=-5).context_window == 8192
    assert compute_budget("s", "u").context_window == 8192


def test_trim_history_keeps_recent_within_budget() -> None:
    history = [
        {"role": "user", "content": "很早的一轮" * 40},
        {"role": "assistant", "content": "较早的回复" * 40},
        {"role": "user", "content": "最近的问题"},
        {"role": "assistant", "content": "最近的回答"},
    ]
    budget = compute_budget("sys", "新输入", context_window=256)
    kept, dropped = trim_history(history, budget)
    assert dropped >= 1  # 长消息被裁
    assert kept  # 至少保住最新若干条
    assert kept[-1]["content"] == "最近的回答"  # 保新
    assert all(m in history for m in kept)  # 不改写内容


def test_trim_history_oversized_latest_keeps_tail() -> None:
    history = [{"role": "assistant", "content": "头" * 500 + "尾" * 50}]
    budget = compute_budget("s", "u", context_window=128)
    kept, _dropped = trim_history(history, budget)
    assert len(kept) == 1
    assert kept[0]["content"].endswith("尾" * 50)
    assert not kept[0]["content"].startswith("头" * 500)


def test_build_context_messages_injects_omission_marker() -> None:
    history = [
        {"role": "user", "content": "旧问题" * 60},
        {"role": "assistant", "content": "旧回答" * 60},
        {"role": "user", "content": "新问题"},
    ]
    messages, _budget, dropped = build_context_messages(
        "人设", history, "本轮输入", context_window=128
    )
    assert dropped == 2  # 两条巨消息均超预算
    assert messages[0] == {"role": "system", "content": "人设"}
    assert messages[1]["content"] == "[较早的对话已省略 2 条]"
    assert messages[-1] == {"role": "user", "content": "本轮输入"}
    # 裁掉的不在消息里
    assert all("旧问题" not in m["content"] for m in messages)


def test_build_context_messages_no_drop_without_marker() -> None:
    history = [{"role": "user", "content": "短"}]
    messages, _budget, dropped = build_context_messages(
        "人设", history, "输入", context_window=8192
    )
    assert dropped == 0
    assert len(messages) == 3
    assert all("省略" not in m["content"] for m in messages)


def test_build_context_messages_empty_history() -> None:
    messages, _budget, dropped = build_context_messages("s", [], "u")
    assert dropped == 0
    assert messages == [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


# ---------------------------------------------------------------------------
# LLMAgentService 装配（4.4 端到端：小窗口裁剪历史）
# ---------------------------------------------------------------------------


class _FakeStore:
    """返回固定历史的假 SessionStore（只实现 recent_messages）。"""

    def __init__(self, messages: list[dict[str, str]]) -> None:
        self._messages = messages

    async def recent_messages(self, session_id: str, limit: int = 20) -> list[dict[str, str]]:
        return self._messages[-limit:]

    async def append_message(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        pass


def _ctx() -> AgentContext:
    return AgentContext(run_id="r-ctx", session_id="s-ctx", text="本轮的问题")


@pytest.mark.asyncio
async def test_agent_trims_history_under_small_window() -> None:
    history = [{"role": "user", "content": f"第{i}轮的很长的问题" * 8} for i in range(6)] + [
        {"role": "assistant", "content": f"第{i}轮的很长的回答" * 8} for i in range(6)
    ]
    model = ScriptedChatModel(calls=[[AIMessageChunk(content="好")]])
    agent = LLMAgentService(
        make_test_adapter(model),
        store=_FakeStore(history),  # type: ignore[arg-type]
        context_window=200,
    )
    events = [e async for e in agent.run(_ctx())]
    assert any(t == "text.delta" for t, _ in events)

    received = model.received[0]
    contents = [m.content for m in received]
    assert any("省略" in c for c in contents)  # 注入省略标记
    assert contents[-1] == "本轮的问题"  # 本轮输入完整保留
    total = sum(estimate_tokens(c) for c in contents)
    assert total < 200  # 总量受控（启发式口径）


@pytest.mark.asyncio
async def test_agent_default_window_no_trim_short_history() -> None:
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你也好"},
    ]
    model = ScriptedChatModel(calls=[[AIMessageChunk(content="好")]])
    agent = LLMAgentService(
        make_test_adapter(model),
        store=_FakeStore(history),  # type: ignore[arg-type]
        checkpointer=InMemorySaver(),
    )
    _ = [e async for e in agent.run(_ctx())]
    contents = [m.content for m in model.received[0]]
    assert "你好" in contents and "你也好" in contents  # 短历史零裁剪
