"""LLMAgentService —— 真实 LLM 的 AgentService 实现（M0-S2，M1-S1 接多轮）。

把 ProviderAdapter 的文本流包装为协议 v0.1 事件序列（§8.1 普通回合时序），
与 EchoAgentService 同构：RunManager 对两者无感。

emotion 策略（ADR-0002 D5）：M0 固定 neutral/0.5；情绪推断推迟 M1。
多轮历史（M1-S1，4.3/6.2）：注入 SessionStore 后，按 session_id 取最近 N 条
消息拼装上下文，回合完成后把本轮 user/assistant 落盘。store 缺省（None）时
保持 M0 单轮行为，向后兼容既有注入路径。
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
from ..store import HISTORY_LIMIT, SessionStore
from .adapters.base import ChatMessage, ProviderAdapter
from .service import AgentContext, AgentEvent, AgentService

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "你是 Mochi，一只温暖可爱的桌面 AI 伙伴。请用自然、亲切、简洁的中文与用户对话，像朋友一样陪伴。"
)


class LLMAgentService(AgentService):
    """组合 ProviderAdapter 与协议事件流。"""

    def __init__(
        self,
        adapter: ProviderAdapter,
        *,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        store: SessionStore | None = None,
    ):
        self._adapter = adapter
        self._system_prompt = system_prompt
        self._store = store

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

        # --- 思考阶段 ---
        # M0：OpenAI 兼容接口无独立推理流，thinking 事件为占位骨架（M1 对话节点打磨）
        yield "state.change", StateChangeData(state="thinking")
        yield "thinking.start", ThinkingStartData(run_id=ctx.run_id, message_id=message_id)
        yield (
            "thinking.delta",
            ThinkingDeltaData(run_id=ctx.run_id, message_id=message_id, delta="让我想想……"),
        )
        yield "thinking.end", ThinkingEndData(run_id=ctx.run_id, message_id=message_id)

        # --- 说话阶段 ---
        yield "state.change", StateChangeData(state="talking")
        yield "emotion", EmotionData(run_id=ctx.run_id, emotion=Emotion.NEUTRAL, intensity=0.5)
        yield "text.start", TextStartData(run_id=ctx.run_id, message_id=message_id)

        # 多轮拼装（6.2）：system + 最近 N 条历史 + 本轮 user（4.4 截断保不报错）
        history = await self._load_history(ctx.session_id)
        messages: list[ChatMessage] = [
            {"role": "system", "content": self._system_prompt},
            *history,
            {"role": "user", "content": ctx.text},
        ]
        parts: list[str] = []
        async for delta in self._adapter.stream_chat(messages, run_id=ctx.run_id):
            parts.append(delta)
            yield "text.delta", TextDeltaData(run_id=ctx.run_id, message_id=message_id, delta=delta)

        full_text = "".join(parts)
        # 落盘本轮（4.3）：仅完整回合入库，取消/出错不落盘
        await self._persist_turn(ctx.session_id, ctx.text, full_text)
        yield (
            "text.end",
            TextEndData(run_id=ctx.run_id, message_id=message_id, full_text=full_text),
        )

        # --- 回到待机 ---
        yield "state.change", StateChangeData(state="idle")
