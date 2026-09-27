"""模型运行时：把 connection + profile + 厂商目录解析成可调用目标。

调用者只选择 profile；端点默认值、协议和凭据归属均在本模块内收敛。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import AppConfig, ResolvedModelTarget
from .model_catalog import get_preset
from .secrets import KeyStore

if TYPE_CHECKING:
    from .agent.adapters.langchain import LangChainAdapter


class ModelRuntime:
    def __init__(self, config: AppConfig, key_store: KeyStore) -> None:
        self._config = config
        self._key_store = key_store

    def update_config(self, config: AppConfig) -> None:
        self._config = config

    def resolve(self, profile_id: str) -> ResolvedModelTarget:
        profile = self._config.model.profiles.get(profile_id)
        if profile is None:
            raise ValueError(f"模型配置 {profile_id} 不存在")
        connection = self._config.model.connections.get(profile.connection_id)
        if connection is None:
            raise ValueError(f"模型连接 {profile.connection_id} 不存在")
        preset = get_preset(connection.preset_id)
        if profile.protocol not in preset.protocols:
            raise ValueError(f"厂商 {preset.display_name} 不支持协议 {profile.protocol}")
        base_url = connection.endpoints.get(profile.protocol) or preset.default_endpoints.get(
            profile.protocol
        )
        return ResolvedModelTarget(
            connection_id=profile.connection_id,
            preset_id=connection.preset_id,
            display_name=profile.display_name,
            protocol=profile.protocol,
            base_url=base_url,
            model=profile.model,
            context_window=profile.context_window,
        )

    def adapter_for(self, profile_id: str) -> LangChainAdapter:
        from .agent.adapters.langchain import LangChainAdapter

        target = self.resolve(profile_id)
        return LangChainAdapter(target.connection_id, target, self._key_store)

    async def probe(
        self, target: ResolvedModelTarget, *, api_key: str | None = None
    ) -> tuple[bool, str]:
        from .agent.adapters.langchain import LangChainAdapter
        from .agent.errors import AgentError

        key_store: KeyStore | _DraftKeyStore = self._key_store
        if api_key:
            key_store = _DraftKeyStore(api_key)
        try:
            adapter = LangChainAdapter(target.connection_id, target, key_store)
        except (AgentError, ValueError) as exc:
            if isinstance(exc, AgentError):
                return False, exc.payload.hint or exc.payload.message
            return False, str(exc)
        return await adapter.ping()


class _DraftKeyStore:
    """草稿测试专用，只存在于一次请求内，不写钥匙串。"""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def get_key(self, connection_id: str) -> str:
        return self._api_key
