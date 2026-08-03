"""Agent 认知核心（M0-S1 echo 桩 → M0-S2 真实模型适配层）。"""

from .adapters import OpenAICompatibleAdapter, ProviderAdapter
from .echo_agent import EchoAgentService
from .errors import AgentError
from .llm_agent import LLMAgentService
from .ollama_probe import OllamaProbeResult, probe_ollama
from .registry import ProviderRegistry
from .run_manager import RunManager
from .service import AgentContext, AgentEvent, AgentService

__all__ = [
    "AgentContext",
    "AgentError",
    "AgentEvent",
    "AgentService",
    "EchoAgentService",
    "LLMAgentService",
    "OllamaProbeResult",
    "OpenAICompatibleAdapter",
    "ProviderAdapter",
    "ProviderRegistry",
    "RunManager",
    "probe_ollama",
]
