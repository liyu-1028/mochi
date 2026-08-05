"""ProviderRegistry 测试：解析、缓存失效、试用兜底、连通性测试。"""

from __future__ import annotations

import pytest

from mochi_server.agent import (
    AgentError,
    AnthropicAdapter,
    EchoAgentService,
    LLMAgentService,
    ProviderRegistry,
)
from mochi_server.config import (
    TRIAL_PROVIDER_ID,
    AppConfig,
    ModelConfig,
    ModelProviderConfig,
)
from mochi_server.secrets import KeyStore


def _config(default: str, providers: dict | None = None) -> AppConfig:
    return AppConfig(model=ModelConfig(default_provider=default, providers=providers or {}))


def _cloud_cfg() -> ModelProviderConfig:
    return ModelProviderConfig(
        kind="openai_compatible",
        display_name="云端",
        base_url="https://api.example.com/v1",
        model="example-chat",
        key_ref="mochi:provider:cloud",
    )


@pytest.fixture
def key_store() -> KeyStore:
    store = KeyStore()
    store.set_key("cloud", "sk-test-12345678")
    return store


def test_trial_provider_resolves_to_echo(key_store):
    registry = ProviderRegistry(_config(TRIAL_PROVIDER_ID), key_store)
    assert isinstance(registry.current_agent(), EchoAgentService)


def test_missing_provider_falls_back_to_trial(key_store):
    registry = ProviderRegistry(_config("ghost"), key_store)
    assert isinstance(registry.current_agent(), EchoAgentService)


def test_openai_compatible_resolves_to_llm_agent(key_store):
    registry = ProviderRegistry(_config("cloud", {"cloud": _cloud_cfg()}), key_store)
    agent = registry.current_agent()
    assert isinstance(agent, LLMAgentService)


def test_agent_cached_until_config_update(key_store):
    registry = ProviderRegistry(_config("cloud", {"cloud": _cloud_cfg()}), key_store)
    first = registry.current_agent()
    assert registry.current_agent() is first  # 同配置命中缓存

    registry.update_config(_config("cloud", {"cloud": _cloud_cfg()}))
    assert registry.current_agent() is not first  # 配置更新 → 缓存失效


def test_missing_key_raises_agent_error_not_crash(key_store):
    cfg = _cloud_cfg()
    cfg.key_ref = "mochi:provider:no_key"  # 钥匙串中不存在
    registry = ProviderRegistry(_config("no_key", {"no_key": cfg}), key_store)
    with pytest.raises(AgentError):
        registry.current_agent()


def test_anthropic_resolves_to_llm_agent(key_store):
    """M1-S0（ADR-0002 D1）：Anthropic 接入，独立适配器。"""
    key_store.set_key("claude", "sk-ant-test")
    cfg = ModelProviderConfig(kind="anthropic", display_name="Claude", model="claude-sonnet-4")
    registry = ProviderRegistry(_config("claude", {"claude": cfg}), key_store)
    agent = registry.current_agent()
    assert isinstance(agent, LLMAgentService)
    assert isinstance(agent.adapter, AnthropicAdapter)


def test_anthropic_missing_key_raises_agent_error_not_crash(key_store):
    cfg = ModelProviderConfig(kind="anthropic", display_name="Claude", model="claude-sonnet-4")
    registry = ProviderRegistry(_config("claude", {"claude": cfg}), key_store)
    with pytest.raises(AgentError):
        registry.current_agent()


@pytest.mark.asyncio
async def test_test_provider_trial_always_ok(key_store):
    registry = ProviderRegistry(_config(TRIAL_PROVIDER_ID), key_store)
    ok, _reason = await registry.test_provider(TRIAL_PROVIDER_ID)
    assert ok is True


@pytest.mark.asyncio
async def test_test_provider_unknown_returns_false(key_store):
    registry = ProviderRegistry(_config(TRIAL_PROVIDER_ID), key_store)
    ok, reason = await registry.test_provider("ghost")
    assert ok is False
    assert "不存在" in reason


@pytest.mark.asyncio
async def test_test_provider_missing_key_reports_hint():
    # 注意：不请求 key_store fixture——需要空钥匙串场景
    cfg = _cloud_cfg()
    registry = ProviderRegistry(_config("cloud", {"cloud": cfg}), KeyStore())
    ok, reason = await registry.test_provider("cloud")
    assert ok is False
    assert "API Key" in reason
