"""AgentService 策略接口 —— 认知核心的可插拔边界。

参照同类项目（Open-LLM-VTuber）的工厂模式：LLM/引擎可替换，
上层（RunManager、WebSocket 管线）只消费标准协议事件。
S2 接入 LangGraph 时只需新增实现，不改管线。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from ..events import CamelModel

# Agent yield 的中间事件：(事件类型, 负载模型)。
# run.started / run.finished 由 RunManager 包裹，Agent 不负责。
AgentEvent = tuple[str, CamelModel]


@dataclass(frozen=True)
class AgentContext:
    """单次对话回合的输入上下文。"""

    run_id: str
    session_id: str
    text: str


class AgentService(ABC):
    """认知核心抽象：输入回合上下文，流式产出协议中间事件。"""

    @abstractmethod
    def run(self, ctx: AgentContext) -> AsyncIterator[AgentEvent]:
        """流式 yield 中间事件。

        约定：
        - 只产出中间事件（state.change / thinking.* / text.* / tool.call.* / emotion）；
        - run.started / run.finished 由 RunManager 统一包裹；
        - 实现方无需处理取消：RunManager 通过 asyncio.Task.cancel() 中断。
        """
