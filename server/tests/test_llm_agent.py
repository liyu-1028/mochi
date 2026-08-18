"""LLMAgentService 测试（M1-S4 图内核）：协议事件序列、工具回环、异常收敛、危险确认。

假模型：fakes.ScriptedChatModel（多回合剧本）。工具回环用例对齐黄金样例
packages/protocol/testdata/turn-with-tool-call.jsonl 的事件时序。
"""

from __future__ import annotations

import asyncio
from typing import Any

import openai
import pytest
from fakes import ScriptedChatModel, make_test_adapter, sdk_error
from langchain_core.messages import AIMessageChunk, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from mochi_server.agent import DangerLevel, LLMAgentService, ToolPolicy, ToolRegistry, ToolSpec
from mochi_server.agent.service import AgentContext
from mochi_server.events import ErrorCode


class EchoArgs(BaseModel):
    text: str


async def _echo(args: dict[str, Any]) -> str:
    return f"回声：{args['text']}"


def _tools() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(name="echo_text", description="回显文本", args_schema=EchoArgs, executor=_echo)
    )
    return registry


def _ctx() -> AgentContext:
    return AgentContext(run_id="r-1", session_id="s-1", text="你好呀")


def _agent(calls: list[list[Any]], *, tool_registry: ToolRegistry | None = None, checkpointer=None):
    model = ScriptedChatModel(calls=calls)
    agent = LLMAgentService(
        make_test_adapter(model),
        tool_registry=tool_registry,
        checkpointer=checkpointer,
    )
    return agent, model


async def _run(agent: LLMAgentService) -> list[tuple[str, object]]:
    return [(t, p) async for t, p in agent.run(_ctx())]


def _types(events: list[tuple[str, object]]) -> list[str]:
    return [t for t, _ in events]


# ---------------------------------------------------------------------------
# 纯对话路径（对齐既有协议时序，行为与换内核前逐事件一致）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_sequence_matches_protocol() -> None:
    agent, _ = _agent([[AIMessageChunk(content="你好，"), AIMessageChunk(content="我是 Mochi")]])
    events = await _run(agent)

    # 无推理流的提供方：thinking 骨架不带 delta（M1-S0 起不再硬编码占位）
    assert _types(events) == [
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
    """真实推理流（content 块 type=thinking）透传为 thinking.delta。"""
    agent, _ = _agent(
        [
            [
                AIMessageChunk(content=[{"type": "thinking", "thinking": "先分析，"}]),
                AIMessageChunk(content=[{"type": "thinking", "thinking": "再回答。"}]),
                AIMessageChunk(content="你好"),
            ]
        ]
    )
    events = await _run(agent)

    assert _types(events) == [
        "state.change",
        "thinking.start",
        "thinking.delta",
        "thinking.delta",
        "thinking.end",
        "state.change",
        "emotion",
        "text.start",
        "text.delta",
        "text.end",
        "state.change",
    ]
    thinking = "".join(p.delta for t, p in events if t == "thinking.delta")
    assert thinking == "先分析，再回答。"
    end = next(p for t, p in events if t == "text.end")
    assert end.full_text == "你好"  # thinking 内容不并入正文


@pytest.mark.asyncio
async def test_thinking_only_response_keeps_sequence_complete() -> None:
    """纯 thinking 无正文：骨架仍完整，text.end.full_text 为空。"""
    agent, _ = _agent([[AIMessageChunk(content=[{"type": "thinking", "thinking": "想岔了"}])]])
    events = await _run(agent)
    assert _types(events)[-3:] == ["text.start", "text.end", "state.change"]
    end = next(p for t, p in events if t == "text.end")
    assert end.full_text == ""


@pytest.mark.asyncio
async def test_emotion_is_neutral_placeholder() -> None:
    """ADR-0002 D5：真实模型固定 neutral/0.5，情绪推断推迟专项。"""
    agent, _ = _agent([[AIMessageChunk(content="嗨")]])
    events = await _run(agent)
    emotion = next(p for t, p in events if t == "emotion")
    assert emotion.emotion == "neutral"
    assert emotion.intensity == 0.5


@pytest.mark.asyncio
async def test_text_deltas_concat_to_full_text() -> None:
    agent, _ = _agent([[AIMessageChunk(content="第一段"), AIMessageChunk(content="第二段")]])
    events = await _run(agent)
    deltas = [p.delta for t, p in events if t == "text.delta"]
    end = next(p for t, p in events if t == "text.end")
    assert "".join(deltas) == end.full_text == "第一段第二段"


@pytest.mark.asyncio
async def test_empty_response_still_emits_start_end() -> None:
    """空内容响应（真实空流至少有一帧空 chunk，langchain 对零帧自抛错）：骨架完整。"""
    agent, _ = _agent([[AIMessageChunk(content="")]])
    events = await _run(agent)
    assert "text.start" in _types(events) and "text.end" in _types(events)
    end = next(p for t, p in events if t == "text.end")
    assert end.full_text == ""


@pytest.mark.asyncio
async def test_model_error_translated_to_agent_error() -> None:
    """图内模型异常经适配层翻译收敛（RunManager 消费 AgentError）。"""
    agent, _ = _agent([[sdk_error(openai.AuthenticationError, 401, "bad key")]])
    with pytest.raises(Exception) as exc_info:
        await _run(agent)
    assert isinstance(exc_info.value, Exception)
    assert getattr(exc_info.value, "payload", None) is not None
    assert exc_info.value.payload.code == ErrorCode.MODEL_AUTH


@pytest.mark.asyncio
async def test_system_prompt_and_user_text_forwarded() -> None:
    model = ScriptedChatModel(calls=[[AIMessageChunk(content="回复")]])
    llm = LLMAgentService(make_test_adapter(model), system_prompt="自定义人设")
    await _run(llm)
    first = model.received[0]
    assert [type(m).__name__ for m in first] == ["SystemMessage", "HumanMessage"]
    assert first[0].content == "自定义人设"
    assert first[1].content == "你好呀"


@pytest.mark.asyncio
async def test_no_tools_registry_skips_bind() -> None:
    """空注册表不 bind_tools：纯对话行为，与黄金样例外的主路径一致。"""
    agent, model = _agent([[AIMessageChunk(content="好")]])
    await _run(agent)
    assert model.bound_tool_names == []


# ---------------------------------------------------------------------------
# 工具回环（对齐黄金样例 turn-with-tool-call.jsonl 时序）
# ---------------------------------------------------------------------------

_TOOL_CALL_CHUNK = AIMessageChunk(
    content="",
    tool_call_chunks=[
        {
            "name": "echo_text",
            "args": '{"text": "嗨"}',
            "id": "tc-1",
            "index": 0,
            "type": "tool_call_chunk",
        }
    ],
)


@pytest.mark.asyncio
async def test_tool_loop_matches_golden_sample() -> None:
    """thinking → working/tool.call → talking/text 的完整时序。"""
    agent, model = _agent(
        [
            [
                AIMessageChunk(content=[{"type": "thinking", "thinking": "需要用工具"}]),
                _TOOL_CALL_CHUNK,
            ],
            [AIMessageChunk(content="结论")],
        ],
        tool_registry=_tools(),
        checkpointer=InMemorySaver(),
    )
    events = await _run(agent)

    assert _types(events) == [
        "state.change",  # thinking
        "thinking.start",
        "thinking.delta",
        "thinking.end",
        "state.change",  # working
        "tool.call.start",
        "tool.call.end",
        "state.change",  # talking
        "emotion",
        "text.start",
        "text.delta",
        "text.end",
        "state.change",  # idle
    ]
    start = next(p for t, p in events if t == "tool.call.start")
    assert start.name == "echo_text"
    assert start.args == {"text": "嗨"}
    end = next(p for t, p in events if t == "tool.call.end")
    assert end.status == "success"
    assert end.result == "回声：嗨"
    # 第二轮 agent 输入含 ToolMessage 回灌
    second = model.received[1]
    assert any(isinstance(m, ToolMessage) and m.content == "回声：嗨" for m in second)


@pytest.mark.asyncio
async def test_tool_failure_maps_to_tool_failed() -> None:
    """执行器异常：tool.call.end status=error + ERR_TOOL_FAILED，回合不中断。"""

    async def _boom(args: dict[str, Any]) -> str:  # pragma: no cover
        raise RuntimeError("磁盘炸了")

    registry = ToolRegistry()
    registry.register(
        ToolSpec(name="echo_text", description="回显", args_schema=EchoArgs, executor=_boom)
    )
    agent, _ = _agent(
        [[_TOOL_CALL_CHUNK], [AIMessageChunk(content="解释失败")]],
        tool_registry=registry,
    )
    events = await _run(agent)

    end = next(p for t, p in events if t == "tool.call.end")
    assert end.status == "error"
    assert end.error.code == ErrorCode.TOOL_FAILED
    assert "磁盘炸了" in end.error.message
    # 回合继续：最终正文仍完整产出
    text_end = next(p for t, p in events if t == "text.end")
    assert text_end.full_text == "解释失败"


# ---------------------------------------------------------------------------
# 危险确认（任务 7，功能清单 6.5）：interrupt 挂起 → tool.confirm → Command 续跑
# ---------------------------------------------------------------------------


class WriteArgs(BaseModel):
    path: str


async def _write_file(args: dict[str, Any]) -> str:
    return f"已写入 {args['path']}"


def _danger_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="write_file",
            description="写文件（危险操作）",
            args_schema=WriteArgs,
            executor=_write_file,
            danger=DangerLevel.DANGEROUS,
        )
    )
    return registry


def _mem_policy() -> tuple[ToolPolicy, dict, list]:
    """内存白名单（load/save 闭包），返回 (policy, 状态盒, save 调用记录)。"""
    state = {"allowed": []}
    saved: list[list[str]] = []

    def _save(names: list[str]) -> None:
        state["allowed"] = list(names)
        saved.append(list(names))

    return ToolPolicy(load=lambda: list(state["allowed"]), save=_save), state, saved


def _danger_call(tc_id: str) -> AIMessageChunk:
    return AIMessageChunk(
        content="",
        tool_call_chunks=[
            {
                "name": "write_file",
                "args": '{"path": "a.txt"}',
                "id": tc_id,
                "index": 0,
                "type": "tool_call_chunk",
            }
        ],
    )


def _danger_agent(
    calls: list[list[Any]], policy: ToolPolicy
) -> tuple[LLMAgentService, ScriptedChatModel]:
    model = ScriptedChatModel(calls=calls)
    agent = LLMAgentService(
        make_test_adapter(model),
        tool_registry=_danger_registry(),
        checkpointer=InMemorySaver(),
        tool_policy=policy,
    )
    return agent, model


async def _collect(agent: LLMAgentService, ctx: AgentContext) -> list[tuple[str, object]]:
    return [event async for event in agent.run(ctx)]


async def _wait_pending(agent: LLMAgentService, run_id: str) -> None:
    """让步事件循环直到挂起出现（上限防死循环）。"""
    for _ in range(500):
        if agent.has_pending(run_id):
            return
        await asyncio.sleep(0)
    raise AssertionError(f"等待挂起超时：run={run_id}")


@pytest.mark.asyncio
async def test_dangerous_tool_pauses_until_allow() -> None:
    """危险工具：挂起等确认，allow 后执行；start 事件不因 resume 重放而重复。"""
    policy, _state, saved = _mem_policy()
    agent, _ = _danger_agent([[_danger_call("tc-9")], [AIMessageChunk(content="写好了")]], policy)
    task = asyncio.create_task(_collect(agent, _ctx()))
    await _wait_pending(agent, "r-1")

    assert await agent.confirm("r-1", "tc-9", "allow", remember=False) is True
    events = await task

    starts = [p for t, p in events if t == "tool.call.start"]
    assert len(starts) == 1  # resume 轮重放去重（实证 2026-08-18）
    assert starts[0].requires_confirmation is True
    assert starts[0].name == "write_file"
    ends = [p for t, p in events if t == "tool.call.end"]
    assert ends[0].status == "success"
    assert ends[0].result == "已写入 a.txt"
    assert saved == []  # 未勾「总是允许」→ 不动白名单
    assert next(p for t, p in events if t == "text.end").full_text == "写好了"


@pytest.mark.asyncio
async def test_dangerous_tool_deny_denies_and_model_recovers() -> None:
    """deny：tool.call.end(status=denied, ERR_TOOL_DENIED)，拒绝事实回灌模型善后。"""
    policy, _state, _saved = _mem_policy()
    agent, model = _danger_agent(
        [[_danger_call("tc-9")], [AIMessageChunk(content="换个方案")]], policy
    )
    task = asyncio.create_task(_collect(agent, _ctx()))
    await _wait_pending(agent, "r-1")

    assert await agent.confirm("r-1", "tc-9", "deny") is True
    events = await task

    end = next(p for t, p in events if t == "tool.call.end")
    assert end.status == "denied"
    assert end.error is not None
    assert end.error.code == ErrorCode.TOOL_DENIED
    # 第二轮模型输入含拒绝善后 ToolMessage（勿重试，换方案）
    second = model.received[1]
    assert any(isinstance(m, ToolMessage) and "拒绝" in m.content for m in second)
    assert next(p for t, p in events if t == "text.end").full_text == "换个方案"


@pytest.mark.asyncio
async def test_allow_with_remember_whitelists_future_calls() -> None:
    """allow + remember：白名单持久化；同 policy 的后续危险调用不再暂停。"""
    policy, _state, saved = _mem_policy()
    agent, _ = _danger_agent([[_danger_call("tc-9")], [AIMessageChunk(content="好")]], policy)
    task = asyncio.create_task(_collect(agent, _ctx()))
    await _wait_pending(agent, "r-1")

    assert await agent.confirm("r-1", "tc-9", "allow", remember=True) is True
    await task
    assert saved == [["write_file"]]

    # 第二回合（新 run）：白名单已生效 → 不暂停，直接执行
    agent2, _ = _danger_agent([[_danger_call("tc-10")], [AIMessageChunk(content="again")]], policy)
    events = await _collect(agent2, AgentContext(run_id="r-2", session_id="s-1", text="再写一次"))
    assert not agent2.has_pending("r-2")
    starts = [p for t, p in events if t == "tool.call.start"]
    assert starts[0].requires_confirmation is False
    ends = [p for t, p in events if t == "tool.call.end"]
    assert ends[0].status == "success"


@pytest.mark.asyncio
async def test_cancel_while_pending_propagates_and_cleans_up() -> None:
    """挂起等待期间 cancel：CancelledError 自然传播，pending 表清理。"""
    policy, _state, _saved = _mem_policy()
    agent, _ = _danger_agent([[_danger_call("tc-9")], [AIMessageChunk(content="不应到达")]], policy)
    task = asyncio.create_task(_collect(agent, _ctx()))
    await _wait_pending(agent, "r-1")

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert agent.has_pending("r-1") is False


@pytest.mark.asyncio
async def test_stale_confirm_rejected() -> None:
    """无匹配挂起（过期/伪造确认）：返回 False 不崩溃。"""
    agent, _ = _agent([[AIMessageChunk(content="好")]])
    assert await agent.confirm("r-1", "tc-x", "allow") is False
