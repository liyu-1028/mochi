"""配置加载/保存/迁移/损坏恢复测试（规范：config-format.md §4/§5/§6）。"""

from __future__ import annotations

import pytest

from mochi_server.config import (
    CONFIG_VERSION,
    TRIAL_PROVIDER_ID,
    AppConfig,
    ConfigError,
    ModelConfig,
    ModelProviderConfig,
    default_config,
    load_config,
    migrate,
    save_config,
)


def _sample_config() -> AppConfig:
    return AppConfig(
        model=ModelConfig(
            default_provider="my_cloud",
            providers={
                "my_cloud": ModelProviderConfig(
                    kind="openai_compatible",
                    display_name="我的云端模型",
                    base_url="https://api.example.com/v1",
                    model="example-chat",
                    key_ref="mochi:provider:my_cloud",
                ),
                "local": ModelProviderConfig(
                    kind="ollama",
                    display_name="Ollama（本地）",
                    model="qwen3:8b",
                    # base_url 为 None：序列化应省略该字段
                ),
            },
        )
    )


def test_first_run_generates_default_with_ollama(tmp_path):
    path = tmp_path / "config.toml"
    config = load_config(path, ollama_available=True, ollama_model="qwen3:8b")

    assert path.exists()  # 生成即落盘
    assert config.model.default_provider == "ollama"
    assert config.model.providers["ollama"].model == "qwen3:8b"


def test_first_run_without_ollama_falls_back_to_trial(tmp_path):
    path = tmp_path / "config.toml"
    config = load_config(path, ollama_available=False)

    assert config.model.default_provider == TRIAL_PROVIDER_ID
    assert config.model.providers == {}


def test_save_load_roundtrip_equivalent(tmp_path):
    path = tmp_path / "config.toml"
    original = _sample_config()
    save_config(path, original)
    loaded = load_config(path)

    assert loaded == original
    # None 字段读回后仍为 None（TOML 中省略，pydantic 默认值补齐）
    assert loaded.model.providers["local"].base_url is None


def test_saved_toml_contains_no_none_literals(tmp_path):
    path = tmp_path / "config.toml"
    save_config(path, _sample_config())
    text = path.read_text(encoding="utf-8")
    assert "None" not in text
    assert "key_ref" in text  # key_ref 正常持久化


def test_corrupt_toml_backed_up_and_default_used(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("这不是合法的 TOML [", encoding="utf-8")

    config = load_config(path)

    assert config.model.default_provider == TRIAL_PROVIDER_ID
    backups = list(tmp_path.glob("config.toml.bak-*"))
    assert len(backups) == 1
    assert "这不是合法的 TOML" in backups[0].read_text(encoding="utf-8")


def test_schema_violation_backed_up(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('config_version = 1\n[model]\ndefault_provider = "ghost"\n', encoding="utf-8")

    config = load_config(path)

    # default_provider 引用不存在的 provider → 校验失败 → 默认配置
    assert config.model.default_provider == TRIAL_PROVIDER_ID
    assert len(list(tmp_path.glob("config.toml.bak-*"))) == 1


def test_backups_pruned_to_three(tmp_path):
    path = tmp_path / "config.toml"
    for i in range(5):
        (tmp_path / f"config.toml.bak-{i}").write_text("stale", encoding="utf-8")
    path.write_text("bad toml [", encoding="utf-8")

    load_config(path)

    assert len(list(tmp_path.glob("config.toml.bak-*"))) == 3


def test_future_version_rejected(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(f"config_version = {CONFIG_VERSION + 1}\n", encoding="utf-8")

    config = load_config(path)

    assert config.config_version == CONFIG_VERSION  # 回退默认配置
    assert len(list(tmp_path.glob("config.toml.bak-*"))) == 1


def test_migrate_noop_for_current_version():
    raw = {"config_version": CONFIG_VERSION, "model": {"default_provider": "trial"}}
    assert migrate(raw)["config_version"] == CONFIG_VERSION


def test_migrate_missing_step_raises():
    # 低于当前版本且无迁移函数 → ConfigError（构造旧版本配置的场景）
    with pytest.raises(ConfigError, match="缺少迁移函数"):
        migrate({"config_version": CONFIG_VERSION - 1})


def test_default_config_trial_is_valid():
    config = default_config()
    assert config.model.default_provider == TRIAL_PROVIDER_ID
