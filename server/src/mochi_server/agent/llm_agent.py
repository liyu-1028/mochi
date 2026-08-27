"""LLMAgentService —— 真实 LLM 的 AgentService 实现（M0-S2 起，M1-S4 换图内核）。

M1-S4（ADR-0008）：内核换为自搭 ReAct 图（react_graph.build_react_graph），
AgentService 接口与 RunManager 零改动——「前后端只依赖协议」红利的兑现。
协议事件序列保持既有形状（黄金样例 packages/protocol/testdata/
turn-with-tool-call.jsonl）：

    state.change(thinking) → thinking.start → [thinking.delta...] → thinking.end
    （若有工具）state.change(working) → tool.call.start → tool.call.end
    state.change(talking) → emotion(neutral) → text.start → [text.delta...]
    → text.end → state.change(idle)

事件桥：graph.astream(stream_mode=["messages","custom"])——messages 通道
的 AIMessageChunk 经 _deltas_from_chunk 分拣为 thinking/text 增量；custom
通道携带 tools 节点实时写出的工具事件。thinking 骨架先行；首个正文增量
收思考、切说话（对齐 M1-S0 起的既有时序）。回环中后续阶段的 thinking
增量在思考已收口后不再补发（协议一回合一条思考流）。

emotion 策略（ADR-0002 D5）：固定 neutral/0.5；真实情绪推断推迟专项。
多轮历史（M1-S1，4.3/6.2）：SessionStore 注入后按 session_id 取最近 N 条
拼装上下文，回合完成后落盘——**历史以 store 为唯一事实源**，checkpoint
thread_id 用 run_id（非 session_id），避免与图内消息双计（ADR-0008 D4）。
记忆（M1-S3，6.4）：MemoryManager 注入后，对话前召回相关记忆注入 system
prompt；当前版本仅手动添加，自动提取留后续版本。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from ..events import (
    Emotion,
    EmotionData,
    ErrorCode,
    ErrorPayload,
    StateChangeData,
    TextDeltaData,
    TextEndData,
    TextStartData,
    ThinkingDeltaData,
    ThinkingEndData,
    ThinkingStartData,
    ToolCallEndData,
    ToolCallStartData,
)
from ..memory import MemoryManager
from ..persona import DEFAULT_SYSTEM_PROMPT
from ..store import HISTORY_LIMIT, SessionStore
from .adapters.base import ChatMessage
from .adapters.langchain import LangChainAdapter, _deltas_from_chunk, _to_lc_messages
from .errors import AgentError
from .react_graph import build_react_graph, is_llm_chunk
from .service import AgentContext, AgentEvent, AgentService
from .tools import ToolPolicy, ToolRegistry

logger = logging.getLogger(__name__)

#: 工具使用提示（M1-S4 任务 9）：小模型带人格 system prompt 时易把工具调用
#: 当纯文本输出甚至编造结果（实测 qwen2.5:1.5b，2026-08-19），绑定工具时追加。
#: 零行为变更：无工具（tool_registry=None）不拼接，黄金样例回放不变。
_TOOL_NUDGE = (
    "\n你可以调用提供的工具完成任务（如查询时间、读取文件）。"
    "需要外部信息或执行操作时务必调用工具，绝不要编造工具结果。"
)


@dataclass
class _PendingConfirm:
    """挂起等待用户裁决的危险工具调用（run_id → 本表）。"""

    tool_call_id: str
    name: str
    future: asyncio.Future[tuple[str, bool]]  # (decision, remember)


class LLMAgentService(AgentService):
    """组合 ReAct 图与协议事件流。"""

    def __init__(
        self,
        adapter: LangChainAdapter,
        *,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        store: SessionStore | None = None,
        memory_manager: MemoryManager | None = None,
        tool_registry: ToolRegistry | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        tool_policy: ToolPolicy | None = None,
    ):
        self._adapter = adapter
        self._system_prompt = system_prompt
        self._store = store
        self._memory = memory_manager
        self._tools = tool_registry  # None → 图不 bind_tools，纯对话行为
        self._checkpointer = checkpointer  # 任务 7 确认暂停/崩溃恢复（ADR-0008 D4）
        self._policy = tool_policy  # None → 危险工具不确认（直接执行）
        self._pending: dict[str, _PendingConfirm] = {}

    @property
    def adapter(self) -> LangChainAdapter:
        return self._adapter

    async def _load_history(self, session_id: str) -> list[ChatMessage]:
        """取最近 N 条历史消息；存储故障降级为无历史，不阻断对话（6.7 优雅降级）。"""
        if self._store is None:
            return []
        try:
            return [
                {"role": m["role"], "content": m["content"]}
                for m in await self._store.recent_messages(session_id, limit=HISTORY_LIMIT)
            ]
        except Exception:
            logger.exception("读取会话历史失败，降级为单轮：session_id=%s", session_id)
            return []

    async def _persist_turn(self, session_id: str, user_text: str, reply: str) -> None:
        if self._store is None:
            return
        try:
            await self._store.append_message(session_id, "user", user_text)
            await self._store.append_message(session_id, "assistant", reply)
        except Exception:
            logger.exception("会话落盘失败（不影响本回合回复）：session_id=%s", session_id)

    async def run(self, ctx: AgentContext) -> AsyncIterator[AgentEvent]:
        message_id = f"m-{uuid.uuid4().hex[:12]}"

        # 记忆召回（6.4）：按用户输入检索相关记忆，注入 system prompt
        memory_section = ""
        if self._memory is not None:
            memory_section = await self._memory.recall_for_prompt(ctx.text)

        # 多轮拼装（6.2）：system + 最近 N 条历史 + 本轮 user（4.4 截断保不报错）
        history = await self._load_history(ctx.session_id)
        effective_system = self._system_prompt + memory_section
        if self._tools is not None and self._tools.list_specs():
            effective_system += _TOOL_NUDGE
        messages: list[ChatMessage] = [
            {"role": "system", "content": effective_system},
            *history,
            {"role": "user", "content": ctx.text},
        ]

        # --- 思考阶段骨架先行（真实推理流经 messages 通道注入） ---
        yield "state.change", StateChangeData(state="thinking")
        yield "thinking.start", ThinkingStartData(run_id=ctx.run_id, message_id=message_id)

        thinking_closed = False
        text_started = False
        parts: list[str] = []

        graph = build_react_graph(
            self._adapter.chat_model,
            self._tools or ToolRegistry(),
            checkpointer=self._checkpointer,
            policy=self._policy,
        )
        config = {"configurable": {"thread_id": ctx.run_id}}
        # 危险确认（任务 7，6.5）：interrupt 挂起 → 流结束 → 等用户裁决 →
        # Command(resume=…) 续跑。resume 会重放 tools 节点（实证 2026-08-18），
        # start 事件按 tool_call_id 去重。
        stream_input: object = {
            "messages": _to_lc_messages(messages, anthropic_style=self._adapter.needs_role_merge)
        }
        emitted_starts: set[str] = set()
        pending_call_id: str | None = None
        pending_name: str = ""
        try:
            while True:
                pending_call_id = None  # 每轮流内跟踪；流结束仍非 None 即挂起
                async for mode, payload in graph.astream(
                    stream_input, config, stream_mode=["messages", "custom"]
                ):
                    if mode == "custom":
                        kind = payload.get("kind")
                        if kind == "tool_call_start":
                            tc_id = payload["tool_call_id"]
                            if tc_id in emitted_starts:
                                continue  # resume 轮重放去重
                            emitted_starts.add(tc_id)
                            if payload.get("requires_confirmation"):
                                pending_call_id = tc_id
                                pending_name = payload["name"]
                                # 竞态修复（任务 9 实测 2026-08-19）：挂起项必须在
                                # 事件发出前注册——客户端最快收到 tool.call.start 即回
                                # tool.confirm，若等流结束才注册（_await_confirmation），
                                # 早到确认会被丢弃 → 回合死锁。图内危险调用顺序处理，
                                # 同一 run 同时至多一个挂起项，单键安全。
                                self._pending[ctx.run_id] = _PendingConfirm(
                                    tc_id,
                                    payload["name"],
                                    asyncio.get_running_loop().create_future(),
                                )
                        elif kind == "tool_call_end" and pending_call_id == payload.get(
                            "tool_call_id"
                        ):
                            pending_call_id = None  # deny 由图内收口，本轮已闭合
                        # 黄金样例时序：thinking.end → state.change(working) → tool.call.start
                        for event_type, event_payload in self._bridge_custom(
                            ctx, payload, message_id, thinking_closed
                        ):
                            if event_type == "thinking.end":
                                thinking_closed = True
                            yield event_type, event_payload
                        continue
                    if not is_llm_chunk(payload):
                        continue
                    chunk: AIMessageChunk = payload[0]
                    for kind, delta in _deltas_from_chunk(chunk):
                        if kind == "thinking":
                            if not thinking_closed:
                                yield (
                                    "thinking.delta",
                                    ThinkingDeltaData(
                                        run_id=ctx.run_id, message_id=message_id, delta=delta
                                    ),
                                )
                        else:
                            if not text_started:
                                # 仅首个正文增量前收思考、切说话（后续 delta 直发）
                                for event_type, event_payload in self._open_text_phase(
                                    ctx, message_id, thinking_closed
                                ):
                                    if event_type == "thinking.end":
                                        thinking_closed = True
                                    elif event_type == "text.start":
                                        text_started = True
                                    yield event_type, event_payload
                            parts.append(delta)
                            yield (
                                "text.delta",
                                TextDeltaData(
                                    run_id=ctx.run_id, message_id=message_id, delta=delta
                                ),
                            )
                if pending_call_id is None:
                    break  # 真完成（或本轮流内已闭合确认）
                # 挂起：等用户裁决。cancel → CancelledError 经 await 自然传播；
                # generator 未结束 → RunManager 不会发 run.finished（暂停非完成）。
                decision, remember = await self._await_confirmation(
                    ctx, pending_call_id, pending_name
                )
                # remember 语义：仅 allow 生效（协议只定义「总是允许」，deny 每次重问）
                if decision == "allow" and remember and self._policy is not None:
                    self._policy.allow_always(pending_name)
                stream_input = Command(resume={"decision": decision})
        except AgentError:
            raise
        except Exception as exc:  # 图内模型异常收敛为 AgentError（RunManager 消费）
            raise self._adapter.translate_error(exc) from exc
        finally:
            # 预注册配套：取消/异常路径也清挂起表（正常路径 _await_confirmation
            # 的 finally 已清，此处兑底幂等）
            self._pending.pop(ctx.run_id, None)

        if not text_started:
            # 空响应（或纯 thinking/纯工具无正文）：仍走完骨架，保协议时序完整
            for event_type, event_payload in self._open_text_phase(
                ctx, message_id, thinking_closed
            ):
                yield event_type, event_payload

        full_text = "".join(parts)
        # 落盘本轮（4.3）：仅完整回合入库，取消/出错不落盘
        await self._persist_turn(ctx.session_id, ctx.text, full_text)
        yield (
            "text.end",
            TextEndData(run_id=ctx.run_id, message_id=message_id, full_text=full_text),
        )

        # --- 回到待机 ---
        yield "state.change", StateChangeData(state="idle")

    # -- 危险确认（任务 7，功能清单 6.5） --------------------------------------

    async def confirm(
        self, run_id: str, tool_call_id: str, decision: str, *, remember: bool = False
    ) -> bool:
        """WS tool.confirm 分发入口；返回 False 表示无匹配的等待中调用（过期确认）。"""
        pending = self._pending.get(run_id)
        if pending is None or pending.tool_call_id != tool_call_id or pending.future.done():
            return False
        pending.future.set_result((decision, remember))
        return True

    def has_pending(self, run_id: str) -> bool:
        """是否存在挂起等待确认的调用（测试同步点）。"""
        return run_id in self._pending

    async def _await_confirmation(
        self, ctx: AgentContext, tool_call_id: str, name: str
    ) -> tuple[str, bool]:
        """等待裁决；返回 (decision, remember)。

        挂起项已在事件发出前预注册（见 run 内竞态修复注释），此处直接消费；
        防御性兑底：缺失/不匹配时重建（理论不可达）。cancel → CancelledError
        经 await 传播（finally 清表）；future 结果由 confirm() 注入。
        """
        pending = self._pending.get(ctx.run_id)
        if pending is None or pending.tool_call_id != tool_call_id:
            future: asyncio.Future[tuple[str, bool]] = asyncio.get_running_loop().create_future()
            self._pending[ctx.run_id] = _PendingConfirm(tool_call_id, name, future)
        else:
            future = pending.future
        try:
            return await future
        finally:
            self._pending.pop(ctx.run_id, None)

    # -- 事件桥辅助 ----------------------------------------------------------

    @staticmethod
    def _open_text_phase(
        ctx: AgentContext, message_id: str, thinking_closed: bool
    ) -> list[AgentEvent]:
        """首个正文增量前的事件组：收思考 → 切说话 → emotion → text.start。"""
        events: list[AgentEvent] = []
        if not thinking_closed:
            events.append(
                ("thinking.end", ThinkingEndData(run_id=ctx.run_id, message_id=message_id))
            )
        events.append(("state.change", StateChangeData(state="talking")))
        events.append(
            ("emotion", EmotionData(run_id=ctx.run_id, emotion=Emotion.NEUTRAL, intensity=0.5))
        )
        events.append(("text.start", TextStartData(run_id=ctx.run_id, message_id=message_id)))
        return events

    @staticmethod
    def _bridge_custom(
        ctx: AgentContext, event: dict, message_id: str, thinking_closed: bool
    ) -> list[AgentEvent]:
        """custom 通道工具事件 → 协议事件（工具前收思考、切工作态）。"""
        kind = event.get("kind")
        if kind == "tool_call_start":
            events: list[AgentEvent] = []
            if not thinking_closed:
                events.append(
                    ("thinking.end", ThinkingEndData(run_id=ctx.run_id, message_id=message_id))
                )
            events.append(("state.change", StateChangeData(state="working")))
            events.append(
                (
                    "tool.call.start",
                    ToolCallStartData(
                        run_id=ctx.run_id,
                        tool_call_id=event["tool_call_id"],
                        name=event["name"],
                        args=event["args"],
                        requires_confirmation=bool(event.get("requires_confirmation")),
                    ),
                ),
            )
            return events
        if kind == "tool_call_end":
            status = event["status"]
            failed = status != "success"
            denied = status == "denied"
            return [
                (
                    "tool.call.end",
                    ToolCallEndData(
                        run_id=ctx.run_id,
                        tool_call_id=event["tool_call_id"],
                        status=status,
                        result=None if failed else event["output"],
                        error=(
                            ErrorPayload(
                                code=ErrorCode.TOOL_DENIED if denied else ErrorCode.TOOL_FAILED,
                                message=event["output"],
                                retryable=not denied,
                            )
                            if failed
                            else None
                        ),
                    ),
                ),
            ]
        logger.warning("未识别的 custom 事件：%s", kind)
        return []
