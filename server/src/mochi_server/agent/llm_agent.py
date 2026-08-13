"""LLMAgentService —— 真实 LLM 的 AgentService 实现（M0-S2，M1-S1 接多轮）。

把 ProviderAdapter 的增量流包装为协议 v0.1 事件序列（§8.1 普通回合时序），
与 EchoAgentService 同构：RunManager 对两者无感。

增量流（M1-S0）：适配层 yield (kind, delta)，kind ∈ {"text", "thinking"}；
thinking 增量透传为协议 thinking.delta（Anthropic 原生推理流），无推理流的
提供方骨架内不带 delta。
emotion 策略（ADR-0002 D5）：固定 neutral/0.5；真实情绪推断推迟 M1 专项。
多轮历史（M1-S1，4.3/6.2）：注入 SessionStore 后，按 session_id 取最近 N 条
消息拼装上下文，回合完成后把本轮 user/assistant 落盘。store 缺省（None）时
保持 M0 单轮行为，向后兼容既有注入路径。
记忆（M1-S3，6.4）：MemoryManager 注入后，对话前按用户输入召回相关记忆注入
system prompt，对话后异步提取沉淀。MemoryManager 缺省（None）时无记忆行为。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator

from ..events import (
    Emotion,
    EmotionData,
    StateChangeData,
    TextDeltaData,
    TextEndData,
    TextStartData,
    ThinkingDeltaData,
    ThinkingEndData,
    ThinkingStartData,
)

# DEFAULT_SYSTEM_PROMPT 权威定义在 persona 模块（提示词内容的领域归属）；
# 此处保留同名再导出，既有 import 路径（llm_agent.DEFAULT_SYSTEM_PROMPT）不变。
from ..memory import MemoryManager
from ..persona import DEFAULT_SYSTEM_PROMPT
from ..store import HISTORY_LIMIT, SessionStore
from .adapters.base import ChatMessage, ProviderAdapter
from .service import AgentContext, AgentEvent, AgentService

logger = logging.getLogger(__name__)


class LLMAgentService(AgentService):
    """组合 ProviderAdapter 与协议事件流。"""

    def __init__(
        self,
        adapter: ProviderAdapter,
        *,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        store: SessionStore | None = None,
        memory_manager: MemoryManager | None = None,
    ):
        self._adapter = adapter
        self._system_prompt = system_prompt
        self._store = store
        self._memory = memory_manager

    @property
    def adapter(self) -> ProviderAdapter:
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
        messages: list[ChatMessage] = [
            {"role": "system", "content": effective_system},
            *history,
            {"role": "user", "content": ctx.text},
        ]

        # --- 思考阶段 ---
        # thinking.* 骨架先行；真实推理流（M1-S0：Anthropic thinking block）
        # 经适配层 ("thinking", delta) 注入。无推理流的提供方骨架内无 delta。
        # emotion 真实推断仍推迟 M1 对话节点打磨专项（ADR-0002 D5）。
        yield "state.change", StateChangeData(state="thinking")
        yield "thinking.start", ThinkingStartData(run_id=ctx.run_id, message_id=message_id)

        text_started = False
        parts: list[str] = []

        async for kind, delta in self._adapter.stream_chat(messages, run_id=ctx.run_id):
            if kind == "thinking":
                yield (
                    "thinking.delta",
                    ThinkingDeltaData(run_id=ctx.run_id, message_id=message_id, delta=delta),
                )
                continue
            if not text_started:
                # 首个正文增量到达：收思考、切说话
                yield "thinking.end", ThinkingEndData(run_id=ctx.run_id, message_id=message_id)
                yield "state.change", StateChangeData(state="talking")
                yield (
                    "emotion",
                    EmotionData(run_id=ctx.run_id, emotion=Emotion.NEUTRAL, intensity=0.5),
                )
                yield "text.start", TextStartData(run_id=ctx.run_id, message_id=message_id)
                text_started = True
            parts.append(delta)
            yield "text.delta", TextDeltaData(run_id=ctx.run_id, message_id=message_id, delta=delta)

        if not text_started:
            # 空响应（或纯 thinking）：仍走完 thinking→说话 骨架，保协议时序完整
            yield "thinking.end", ThinkingEndData(run_id=ctx.run_id, message_id=message_id)
            yield "state.change", StateChangeData(state="talking")
            yield "emotion", EmotionData(run_id=ctx.run_id, emotion=Emotion.NEUTRAL, intensity=0.5)
            yield "text.start", TextStartData(run_id=ctx.run_id, message_id=message_id)

        full_text = "".join(parts)
        # 落盘本轮（4.3）：仅完整回合入库，取消/出错不落盘
        await self._persist_turn(ctx.session_id, ctx.text, full_text)
        # 记忆沉淀（6.4）：异步提取值得记住的事实/偏好，失败静默降级
        if self._memory is not None:
            await self._memory.extract_and_store(self._adapter, ctx.text, full_text)
        yield (
            "text.end",
            TextEndData(run_id=ctx.run_id, message_id=message_id, full_text=full_text),
        )

        # --- 回到待机 ---
        yield "state.change", StateChangeData(state="idle")
