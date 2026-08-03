"""EchoAgentService —— M0-S1 桩模型。

不调用任何真实 LLM，按协议时序回显用户输入，用于：
- 验证端到端事件管线（握手 → 流式 → 取消）
- 前端开发不依赖模型 Key / 本地 Ollama
事件序列严格遵循协议文档 §8.1 的普通回合时序。
"""

from __future__ import annotations

import asyncio
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
from .service import AgentContext, AgentEvent, AgentService

_CHUNK_SIZE = 4  # 每个 text.delta 的字符数


class EchoAgentService(AgentService):
    """回显桩：模拟 思考 → 说话 的完整事件序列。"""

    def __init__(self, chunk_delay: float = 0.03, thinking_delay: float = 0.15) -> None:
        # 延迟可在测试中置 0 加速
        self._chunk_delay = chunk_delay
        self._thinking_delay = thinking_delay

    async def run(self, ctx: AgentContext) -> AsyncIterator[AgentEvent]:
        message_id = f"m-{uuid.uuid4().hex[:12]}"

        # --- 思考阶段（驱动角色 thinking 动画）---
        yield "state.change", StateChangeData(state="thinking")
        yield "thinking.start", ThinkingStartData(run_id=ctx.run_id, message_id=message_id)
        thought = f"用户说：「{ctx.text}」，我来原样回应……"
        for i in range(0, len(thought), _CHUNK_SIZE * 2):
            if self._thinking_delay:
                await asyncio.sleep(self._thinking_delay)
            yield (
                "thinking.delta",
                ThinkingDeltaData(
                    run_id=ctx.run_id, message_id=message_id, delta=thought[i : i + _CHUNK_SIZE * 2]
                ),
            )
        yield "thinking.end", ThinkingEndData(run_id=ctx.run_id, message_id=message_id)

        # --- 说话阶段 ---
        yield "state.change", StateChangeData(state="talking")
        yield "emotion", EmotionData(run_id=ctx.run_id, emotion=Emotion.HAPPY, intensity=0.6)

        reply = (
            f"收到你的消息：「{ctx.text}」。"
            "我是 Mochi 的 echo 桩模型，端到端链路已打通，真实模型将在 S2 接入。"
        )
        yield "text.start", TextStartData(run_id=ctx.run_id, message_id=message_id)
        for i in range(0, len(reply), _CHUNK_SIZE):
            if self._chunk_delay:
                await asyncio.sleep(self._chunk_delay)
            yield (
                "text.delta",
                TextDeltaData(
                    run_id=ctx.run_id, message_id=message_id, delta=reply[i : i + _CHUNK_SIZE]
                ),
            )
        yield "text.end", TextEndData(run_id=ctx.run_id, message_id=message_id, full_text=reply)

        # --- 回到待机 ---
        yield "state.change", StateChangeData(state="idle")
