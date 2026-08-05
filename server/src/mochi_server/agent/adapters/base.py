"""ProviderAdapter —— 模型提供方薄接口（ADR-0002 D4）。

层级约定：``RunManager → AgentService（LLM/Echo）→ ProviderAdapter → SDK``。
适配器只负责两件事：调用 LLM、把 SDK 异常翻译成 AgentError。

流增量带类型标签（M1-S0，Anthropic 原生 thinking block 驱动）：
``stream_chat`` yield ``(kind, delta)``，kind ∈ {"text", "thinking"}。
无独立推理流的提供方（OpenAI 兼容 / Ollama）恒 yield ``("text", ...)``；
LLMAgentService 据此把真实推理流转为协议 thinking.* 事件。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Literal

ChatMessage = dict[str, str]

#: 流增量类型：正文 / 推理过程（thinking）
StreamKind = Literal["text", "thinking"]


class ProviderAdapter(ABC):
    """模型提供方适配器。实现必须把所有异常收敛为 AgentError。"""

    @abstractmethod
    def stream_chat(
        self, messages: list[ChatMessage], *, run_id: str
    ) -> AsyncIterator[tuple[StreamKind, str]]:
        """流式 yield (类型, 文本增量)；异常统一翻译为 AgentError（含可读 hint）。"""

    @abstractmethod
    async def ping(self) -> tuple[bool, str]:
        """连通性测试（功能清单 7.2）：返回 (是否可用, 可读原因/引导)。"""
