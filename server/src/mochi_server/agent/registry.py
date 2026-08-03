"""ProviderRegistry —— 模型热切换（ADR-0002 D4）。

职责：按 ``config.model.default_provider`` 解析当前 AgentService；
配置更新后无需重启即生效（版本号缓存失效）。

解析规则：
- ``trial`` → EchoAgentService（试用模式，功能清单 1.5）
- ``ollama`` / ``openai_compatible`` → LLMAgentService(OpenAICompatibleAdapter)
- ``anthropic`` → 解析期 AgentError（M1 实现，友好提示而非崩溃）
- default_provider 引用缺失 → 回退试用模式（可用性优先）
"""

from __future__ import annotations

import logging

from ..config import TRIAL_PROVIDER_ID, AppConfig, ModelProviderConfig
from ..events import ErrorCode, ErrorPayload
from ..secrets import KeyStore
from .adapters import OpenAICompatibleAdapter
from .echo_agent import EchoAgentService
from .errors import AgentError
from .llm_agent import LLMAgentService
from .service import AgentService

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """每个 sidecar 进程一个实例；配置变更经 update_config 注入。"""

    def __init__(self, config: AppConfig, key_store: KeyStore | None = None) -> None:
        self._config = config
        self._key_store = key_store or KeyStore()
        self._version = 0  # 配置版本号：update_config 递增，驱动缓存失效
        self._agent_cache: tuple[int, str, AgentService] | None = None
        self._trial = EchoAgentService()

    # -- 配置 ----------------------------------------------------------------

    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def key_store(self) -> KeyStore:
        return self._key_store

    def update_config(self, config: AppConfig) -> None:
        """整包替换配置并使适配器缓存失效（下一回合即用新配置）。"""
        self._config = config
        self._version += 1
        self._agent_cache = None

    # -- 解析 ----------------------------------------------------------------

    def current_agent(self) -> AgentService:
        """解析当前回合使用的 AgentService；可能抛 AgentError（由 RunManager 捕获）。"""
        provider_id = self._config.model.default_provider
        if provider_id == TRIAL_PROVIDER_ID:
            return self._trial

        cfg = self._config.model.providers.get(provider_id)
        if cfg is None:
            logger.warning("default_provider=%s 未定义，回退试用模式", provider_id)
            return self._trial

        cache = self._agent_cache
        if cache is not None and cache[0] == self._version and cache[1] == provider_id:
            return cache[2]

        agent = self._build_agent(provider_id, cfg)
        self._agent_cache = (self._version, provider_id, agent)
        return agent

    def _build_agent(self, provider_id: str, cfg: ModelProviderConfig) -> AgentService:
        if cfg.kind == "anthropic":
            raise AgentError(
                ErrorPayload(
                    code=ErrorCode.MODEL_UNAVAILABLE,
                    message="Anthropic 支持还在路上",
                    retryable=False,
                    hint="M1 版本将接入 Anthropic；请先选用 OpenAI 兼容接口或 Ollama",
                )
            )
        # 缺 Key 等构造期问题在此抛 AgentError，由 RunManager 转为 run.error
        adapter = OpenAICompatibleAdapter(provider_id, cfg, self._key_store)
        return LLMAgentService(adapter)

    # -- 连通性测试（功能清单 7.2） ------------------------------------------

    async def test_provider(self, provider_id: str) -> tuple[bool, str]:
        if provider_id == TRIAL_PROVIDER_ID:
            return True, "试用模式始终可用"
        cfg = self._config.model.providers.get(provider_id)
        if cfg is None:
            return False, f"提供方 {provider_id} 不存在"
        if cfg.kind == "anthropic":
            return False, "Anthropic 支持将在 M1 版本接入"
        try:
            adapter = OpenAICompatibleAdapter(provider_id, cfg, self._key_store)
        except AgentError as exc:
            return False, exc.payload.hint or exc.payload.message
        return await adapter.ping()
