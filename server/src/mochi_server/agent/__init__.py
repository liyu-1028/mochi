"""Agent 认知核心（M0-S1 echo 桩 → M0-S2 真实模型适配层）。"""

from .adapters import OpenAICompatibleAdapter, ProviderAdapter
from .echo_agent import EchoAgentService
from .errors import AgentError
from .llm_agent import LLMAgentService
from .run_manager import RunManager
from .service import AgentContext, AgentEvent, AgentService

__all__ = [
    "AgentContext",
    "AgentError",
    "AgentEvent",
    "AgentService",
    "EchoAgentService",
    "LLMAgentService",
    "OpenAICompatibleAdapter",
    "ProviderAdapter",
    "RunManager",
]
