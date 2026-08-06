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


# ---------------------------------------------------------------------------
# 人格注入（功能清单 6.13，ADR-0005）
# ---------------------------------------------------------------------------


def test_empty_persona_uses_default_prompt(key_store):
    from mochi_server.persona import DEFAULT_SYSTEM_PROMPT

    registry = ProviderRegistry(_config("cloud", {"cloud": _cloud_cfg()}), key_store)
    agent = registry.current_agent()
    assert agent._system_prompt == DEFAULT_SYSTEM_PROMPT


def test_persona_injected_into_system_prompt(key_store):
    config = _config("cloud", {"cloud": _cloud_cfg()})
    config.character.persona.soul_preset = "warm_sun"
    config.character.persona.style_custom = "说话像海盗"
    registry = ProviderRegistry(config, key_store)

    prompt = registry.current_agent()._system_prompt
    assert "【灵魂设定】" in prompt
    assert "温暖治愈" in prompt  # warm_sun 预设文案
    assert "【说话风格】" in prompt
    assert "说话像海盗" in prompt  # custom 注入
    assert "【性格特征】" not in prompt  # 未配置的维度不出现


def test_persona_update_rebuilds_agent_prompt(key_store):
    registry = ProviderRegistry(_config("cloud", {"cloud": _cloud_cfg()}), key_store)
    first = registry.current_agent()

    new_config = _config("cloud", {"cloud": _cloud_cfg()})
    new_config.character.persona.personality_preset = "tsundere_cat"
    registry.update_config(new_config)

    second = registry.current_agent()
    assert second is not first  # 缓存失效重建
    assert "傲娇" in second._system_prompt
    assert "傲娇" not in first._system_prompt


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
