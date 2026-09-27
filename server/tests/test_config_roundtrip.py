"""配置加载/保存/迁移/损坏恢复测试（规范：config-format.md §4/§5/§6）。"""

from __future__ import annotations

import pytest

from mochi_server.config import (
    CONFIG_VERSION,
    TRIAL_PROFILE_ID,
    AppConfig,
    ConfigError,
    ModelConfig,
    ModelConnectionConfig,
    ModelProfileConfig,
    default_config,
    load_config,
    migrate,
    save_config,
)


def _sample_config() -> AppConfig:
    return AppConfig(
        model=ModelConfig(
            default_profile="my_cloud",
            connections={
                "my_cloud": ModelConnectionConfig(
                    preset_id="custom",
                    display_name="我的云端账号",
                    endpoints={"openai_chat": "https://api.example.com/v1"},
                    key_ref="mochi:provider:my_cloud",
                ),
                "local": ModelConnectionConfig(
                    preset_id="ollama",
                    display_name="Ollama（本地）",
                ),
            },
            profiles={
                "my_cloud": ModelProfileConfig(
                    connection_id="my_cloud",
                    display_name="我的云端模型",
                    protocol="openai_chat",
                    model="example-chat",
                ),
                "local": ModelProfileConfig(
                    connection_id="local",
                    display_name="qwen3:8b",
                    protocol="openai_chat",
                    model="qwen3:8b",
                ),
            },
        )
    )


def test_first_run_generates_default_with_ollama(tmp_path):
    path = tmp_path / "config.toml"
    config = load_config(path, ollama_available=True, ollama_model="qwen3:8b")

    assert path.exists()
    assert config.model.default_profile == "ollama"
    assert config.model.connections["ollama"].preset_id == "ollama"
    assert config.model.profiles["ollama"].model == "qwen3:8b"


def test_first_run_without_ollama_falls_back_to_trial(tmp_path):
    path = tmp_path / "config.toml"
    config = load_config(path, ollama_available=False)

    assert config.model.default_profile == TRIAL_PROFILE_ID
    assert config.model.connections == {}
    assert config.model.profiles == {}


def test_save_load_roundtrip_equivalent(tmp_path):
    path = tmp_path / "config.toml"
    original = _sample_config()
    save_config(path, original)
    loaded = load_config(path)

    assert loaded == original
    assert loaded.model.connections["local"].endpoints == {}


def test_saved_toml_contains_no_none_literals(tmp_path):
    path = tmp_path / "config.toml"
    save_config(path, _sample_config())
    text = path.read_text(encoding="utf-8")
    assert "None" not in text
    assert "key_ref" in text


def test_v1_provider_config_migrates_to_connection_and_profile(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """config_version = 1

[model]
default_provider = "cloud"

[model.providers.cloud]
kind = "openai_responses"
display_name = "智谱 GLM"
base_url = "https://open.bigmodel.cn/api/v1"
model = "glm-5.3-flash"
key_ref = "mochi:provider:cloud"
context_window = 131072
""",
        encoding="utf-8",
    )

    loaded = load_config(path)

    assert loaded.config_version == 2
    assert loaded.model.default_profile == "cloud"
    connection = loaded.model.connections["cloud"]
    assert connection.preset_id == "zhipu"
    assert connection.key_ref == "mochi:provider:cloud"
    assert connection.endpoints == {"openai_responses": "https://open.bigmodel.cn/api/v1"}
    profile = loaded.model.profiles["cloud"]
    assert profile.connection_id == "cloud"
    assert profile.protocol == "openai_responses"
    assert profile.model == "glm-5.3-flash"
    assert profile.context_window == 131072
    persisted = path.read_text(encoding="utf-8")
    assert "config_version = 2" in persisted
    assert 'default_profile = "cloud"' in persisted
    assert "providers" not in persisted


def test_persona_roundtrip(tmp_path):
    from mochi_server.config import PersonaConfig

    path = tmp_path / "config.toml"
    original = _sample_config()
    original.character.persona = PersonaConfig(soul_preset="warm_sun", style_custom="说话像海盗")
    save_config(path, original)
    loaded = load_config(path)
    assert loaded.character.persona.soul_preset == "warm_sun"
    assert loaded.character.persona.style_custom == "说话像海盗"
    assert loaded.character.persona.personality_preset == ""


def test_current_config_without_persona_gets_default(tmp_path):
    """旧字段缺失时由 pydantic 默认值补齐，无需新增迁移。"""
    import tomli_w

    from mochi_server.config import PersonaConfig

    raw = _sample_config().model_dump(mode="json", exclude_none=True)
    del raw["character"]["persona"]
    path = tmp_path / "config.toml"
    path.write_text(tomli_w.dumps(raw), encoding="utf-8")

    loaded = load_config(path)
    assert loaded.character.persona == PersonaConfig()


def test_corrupt_toml_backed_up_and_default_used(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("这不是合法的 TOML [", encoding="utf-8")

    config = load_config(path)

    assert config.model.default_profile == TRIAL_PROFILE_ID
    backups = list(tmp_path.glob("config.toml.bak-*"))
    assert len(backups) == 1
    assert "这不是合法的 TOML" in backups[0].read_text(encoding="utf-8")


def test_schema_violation_backed_up(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('config_version = 2\n[model]\ndefault_profile = "ghost"\n', encoding="utf-8")

    config = load_config(path)

    assert config.model.default_profile == TRIAL_PROFILE_ID
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

    assert config.config_version == CONFIG_VERSION
    assert len(list(tmp_path.glob("config.toml.bak-*"))) == 1


def test_migrate_noop_for_current_version():
    raw = {"config_version": CONFIG_VERSION, "model": {"default_profile": "trial"}}
    assert migrate(raw) == raw


def test_migrate_missing_step_raises():
    with pytest.raises(ConfigError, match="缺少迁移函数"):
        migrate({"config_version": 0})


def test_default_config_trial_is_valid():
    config = default_config()
    assert config.model.default_profile == TRIAL_PROFILE_ID
