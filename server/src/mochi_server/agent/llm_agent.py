"""LLMAgentService —— 真实 LLM 的 AgentService 实现（M0-S2）。

把 ProviderAdapter 的文本流包装为协议 v0.1 事件序列（§8.1 普通回合时序），
与 EchoAgentService 同构：RunManager 对两者无感。

emotion 策略（ADR-0002 D5）：M0 固定 neutral/0.5；情绪推断推迟 M1。
多轮历史：M0 单轮（每条消息独立上下文）；会话持久化与上下文管理见 S5（4.3/4.4）。
"""

from __future__ import annotations

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
from .adapters.base import ChatMessage, ProviderAdapter
from .service import AgentContext, AgentEvent, AgentService

DEFAULT_SYSTEM_PROMPT = (
    "你是 Mochi，一只温暖可爱的桌面 AI 伙伴。请用自然、亲切、简洁的中文与用户对话，像朋友一样陪伴。"
)


class LLMAgentService(AgentService):
    """组合 ProviderAdapter 与协议事件流。"""

    def __init__(self, adapter: ProviderAdapter, *, system_prompt: str = DEFAULT_SYSTEM_PROMPT):
        self._adapter = adapter
        self._system_prompt = system_prompt

    @property
    def adapter(self) -> ProviderAdapter:
        return self._adapter

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

        messages: list[ChatMessage] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": ctx.text},
        ]
        parts: list[str] = []
        async for delta in self._adapter.stream_chat(messages, run_id=ctx.run_id):
            parts.append(delta)
            yield "text.delta", TextDeltaData(run_id=ctx.run_id, message_id=message_id, delta=delta)

        yield (
            "text.end",
            TextEndData(run_id=ctx.run_id, message_id=message_id, full_text="".join(parts)),
        )

        # --- 回到待机 ---
        yield "state.change", StateChangeData(state="idle")
