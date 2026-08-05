"""模型提供方适配器（ADR-0002 D1/D4：SDK 细节收敛在本包内）。"""

from .anthropic import AnthropicAdapter
from .base import ProviderAdapter
from .openai_compat import OpenAICompatibleAdapter

__all__ = ["AnthropicAdapter", "OpenAICompatibleAdapter", "ProviderAdapter"]
