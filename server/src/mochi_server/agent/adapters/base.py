"""ProviderAdapter —— 模型提供方薄接口（ADR-0002 D4）。

层级约定：``RunManager → AgentService（LLM/Echo）→ ProviderAdapter → SDK``。
适配器只负责两件事：调用 LLM、把 SDK 异常翻译成 AgentError。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

ChatMessage = dict[str, str]


class ProviderAdapter(ABC):
    """模型提供方适配器。实现必须把所有异常收敛为 AgentError。"""

    @abstractmethod
    def stream_chat(self, messages: list[ChatMessage], *, run_id: str) -> AsyncIterator[str]:
        """流式 yield 文本增量；异常统一翻译为 AgentError（含可读 hint）。"""

    @abstractmethod
    async def ping(self) -> tuple[bool, str]:
        """连通性测试（功能清单 7.2）：返回 (是否可用, 可读原因/引导)。"""
