"""用户配置 schema 与读写（规范：docs/specs/config-format.md）。

原则：
- sidecar 是配置的唯一事实源，前端经 RPC 读写，不直接碰文件；
- TOML 存储、pydantic 校验、原子写入（tmp + os.replace）；
- 敏感信息（API Key）只存 key_ref（系统钥匙串条目名），永不落明文。
"""

from __future__ import annotations

import logging
import os
import threading
import time
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import tomli_w
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

CONFIG_VERSION = 1

ProviderKind = Literal["ollama", "openai_compatible", "anthropic"]

# 界面语言（功能清单 7.8 的 M1 前置：设置项先行，文案双语化在桌面端）。
Language = Literal["zh-CN", "en"]

# 试用模式：内置 echo 桩（功能清单 1.5），不在 providers 表中持久化。
TRIAL_PROVIDER_ID = "trial"

OLLAMA_DEFAULT_BASE_URL = "http://127.0.0.1:11434"

# 损坏配置备份保留份数（§4.4）。
_MAX_BACKUPS = 3

_WRITE_LOCK = threading.Lock()


class ConfigError(ValueError):
    """配置读取/校验/迁移失败。"""


class GeneralConfig(BaseModel):
    language: Language = "zh-CN"
    launch_at_startup: bool = False
    telemetry: bool = False


class PersonaConfig(BaseModel):
    """人格设定（功能清单 6.13，ADR-0005）：三维度各一对字段。

    `{soul,personality,style}_preset` 引用内置预设 id（空串 = 未选择），
    `_custom` 为用户自定义文本（非空时覆盖 preset）。全空 = 默认人设。
    """

    soul_preset: str = ""
    soul_custom: str = Field(default="", max_length=500)
    personality_preset: str = ""
    personality_custom: str = Field(default="", max_length=500)
    style_preset: str = ""
    style_custom: str = Field(default="", max_length=500)


class CharacterConfig(BaseModel):
    active_skin: str = "default"
    persona: PersonaConfig = Field(default_factory=PersonaConfig)


class ModelProviderConfig(BaseModel):
    kind: ProviderKind
    display_name: str
    base_url: str | None = None
    model: str
    key_ref: str | None = None  # 系统钥匙串条目名；ollama 通常无需


class ModelConfig(BaseModel):
    default_provider: str = TRIAL_PROVIDER_ID
    providers: dict[str, ModelProviderConfig] = Field(default_factory=dict)


class VoiceConfig(BaseModel):
    tts_enabled: bool = True
    engine: Literal["edge", "local"] = "edge"
    voice_id: str = "zh-CN-XiaoxiaoNeural"
    volume: float = Field(default=1.0, ge=0.0, le=1.0)
    rate: float = Field(default=1.0, ge=0.5, le=2.0)
    muted: bool = False


class PrivacyConfig(BaseModel):
    local_only: bool = False


class SkillsConfig(BaseModel):
    enabled: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    config_version: int = CONFIG_VERSION
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    character: CharacterConfig = Field(default_factory=CharacterConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)


# ---------------------------------------------------------------------------
# 默认配置（Zero Config 关键路径，规范 §6）
# ---------------------------------------------------------------------------


def default_config(*, ollama_available: bool = False, ollama_model: str | None = None) -> AppConfig:
    """首次启动的默认配置。

    探测到 Ollama 且有可用模型 → 预填 ollama provider 并设为默认；
    否则空 provider 表，默认走试用模式（echo 桩）。
    """
    config = AppConfig()
    if ollama_available and ollama_model:
        config.model.providers["ollama"] = ModelProviderConfig(
            kind="ollama",
            display_name="Ollama（本地）",
            base_url=OLLAMA_DEFAULT_BASE_URL,
            model=ollama_model,
        )
        config.model.default_provider = "ollama"
    return config


# ---------------------------------------------------------------------------
# 版本迁移（规范 §4）
# ---------------------------------------------------------------------------

# config_version N → N+1 的迁移函数注册表；迁移必须幂等且只增不删。
_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """按迁移链把 raw 升级到当前 CONFIG_VERSION。"""
    version = raw.get("config_version", CONFIG_VERSION)
    if not isinstance(version, int):
        raise ConfigError(f"config_version 非法：{version!r}")
    if version > CONFIG_VERSION:
        raise ConfigError(f"配置来自更高版本（{version} > {CONFIG_VERSION}），拒绝降级读取")
    while version < CONFIG_VERSION:
        step = _MIGRATIONS.get(version)
        if step is None:
            raise ConfigError(f"缺少迁移函数：v{version} → v{version + 1}")
        raw = step(raw)
        version += 1
        raw["config_version"] = version
    return raw


def _validate_provider_reference(config: AppConfig) -> None:
    """default_provider 必须存在于 providers（trial 为隐式内置）。"""
    default = config.model.default_provider
    if default != TRIAL_PROVIDER_ID and default not in config.model.providers:
        raise ConfigError(f"default_provider={default!r} 未在 providers 中定义")


# ---------------------------------------------------------------------------
# 读写（规范 §4/§5）
# ---------------------------------------------------------------------------


def load_config(
    path: Path,
    *,
    ollama_available: bool = False,
    ollama_model: str | None = None,
) -> AppConfig:
    """读取并校验配置；文件不存在时生成默认配置并落盘。

    损坏/校验失败：备份为 ``config.toml.bak-<ts>``（保留最近 _MAX_BACKUPS 份），
    以默认配置重启（规范 §4.4；UI 提示由调用方负责）。
    """
    if not path.exists():
        config = default_config(ollama_available=ollama_available, ollama_model=ollama_model)
        save_config(path, config)
        return config

    try:
        with path.open("rb") as f:
            raw = tomllib.load(f)
        raw = migrate(raw)
        config = AppConfig.model_validate(raw)
        _validate_provider_reference(config)
        return config
    except (OSError, tomllib.TOMLDecodeError, ValidationError, ConfigError) as exc:
        logger.warning("配置加载失败（%s），备份后使用默认配置：%s", exc, path)
        _backup_corrupt(path)
        config = default_config(ollama_available=ollama_available, ollama_model=ollama_model)
        save_config(path, config)
        return config


def save_config(path: Path, config: AppConfig) -> None:
    """原子写入：tomli_w 序列化 → 同目录 tmp 文件 → os.replace。

    None 字段（如未设置的 base_url）序列化时省略，读回时由 pydantic 默认值补齐。
    """
    payload = tomli_w.dumps(config.model_dump(mode="json", exclude_none=True))
    with _WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)


def _backup_corrupt(path: Path) -> None:
    backup = path.with_name(f"{path.name}.bak-{int(time.time())}")
    try:
        path.rename(backup)
    except OSError as exc:
        logger.warning("损坏配置备份失败：%s", exc)
        return
    _prune_backups(path)


def _prune_backups(path: Path) -> None:
    backups = sorted(path.parent.glob(f"{path.name}.bak-*"))
    for stale in backups[:-_MAX_BACKUPS]:
        stale.unlink(missing_ok=True)
