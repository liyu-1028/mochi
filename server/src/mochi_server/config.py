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
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

import tomli_w
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

CONFIG_VERSION = 2

# 厂商和通信协议是两个独立概念：同一厂商可同时提供 Chat Completions 与
# Responses；一个连接（账号/Key）可挂多个模型配置。
WireProtocol = Literal["openai_chat", "openai_responses", "anthropic_messages"]

# 界面语言（功能清单 7.8 的 M1 前置：设置项先行，文案双语化在桌面端）。
Language = Literal["zh-CN", "en"]

# 试用模式：内置 echo 桩（功能清单 1.5），不在 profiles 表中持久化。
TRIAL_PROFILE_ID = "trial"

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
    # 省电模式（2.6 性能护栏）：true → 角色渲染钉 15fps + 暂停装饰动画
    power_save: bool = False


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


class ModelConnectionConfig(BaseModel):
    """一个厂商账号或本地实例；Key 与端点在多个模型间共享。"""

    preset_id: str
    display_name: str
    endpoints: dict[WireProtocol, str] = Field(default_factory=dict)
    key_ref: str | None = None


class ModelProfileConfig(BaseModel):
    """一个可被设为默认项的具体模型。"""

    connection_id: str
    display_name: str
    protocol: WireProtocol
    model: str
    context_window: int | None = None  # token 窗口（4.4 预算裁剪）；None → 缺省 8192


class ResolvedModelTarget(BaseModel):
    """运行时已解析的模型目标；调用方无需再理解目录默认值。"""

    connection_id: str
    preset_id: str
    display_name: str
    protocol: WireProtocol
    base_url: str | None = None
    model: str
    context_window: int | None = None


class ModelConfig(BaseModel):
    default_profile: str = TRIAL_PROFILE_ID
    connections: dict[str, ModelConnectionConfig] = Field(default_factory=dict)
    profiles: dict[str, ModelProfileConfig] = Field(default_factory=dict)


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


class MemoryConfig(BaseModel):
    """记忆行为开关（6.4：自动沉淀 v0.8.1 重开，带质量闸门）。"""

    auto_extract: bool = True  # 对话后自动提取记忆；False → 仅手动


class AgentConfig(BaseModel):
    """认知行为开关（2.5 情绪推断，ADR-0009）。"""

    emotion: Literal["auto", "off"] = "auto"  # 回复后置情绪分类；off → 恒 neutral


class ToolsConfig(BaseModel):
    """工具授权（M1-S4，功能清单 6.5）：dangerous 工具的「总是允许」白名单。"""

    allowed: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    config_version: int = CONFIG_VERSION
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    character: CharacterConfig = Field(default_factory=CharacterConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)


# ---------------------------------------------------------------------------
# 默认配置（Zero Config 关键路径，规范 §6）
# ---------------------------------------------------------------------------


def default_config(*, ollama_available: bool = False, ollama_model: str | None = None) -> AppConfig:
    """首次启动的默认配置。

    探测到 Ollama 且有可用模型 → 预填连接与模型配置并设为默认；
    否则保持空配置，默认走试用模式（echo 桩）。
    """
    config = AppConfig()
    if ollama_available and ollama_model:
        config.model.connections["ollama"] = ModelConnectionConfig(
            preset_id="ollama",
            display_name="Ollama（本地）",
            endpoints={"openai_chat": OLLAMA_DEFAULT_BASE_URL},
        )
        config.model.profiles["ollama"] = ModelProfileConfig(
            connection_id="ollama",
            display_name=ollama_model,
            protocol="openai_chat",
            model=ollama_model,
        )
        config.model.default_profile = "ollama"
    return config


# ---------------------------------------------------------------------------
# 版本迁移（规范 §4）
# ---------------------------------------------------------------------------


def _infer_preset_id(kind: str, base_url: str | None) -> str:
    if kind == "ollama":
        return "ollama"
    if kind == "anthropic":
        return "anthropic"
    url = (base_url or "").lower()
    if "dashscope" in url or "maas.aliyuncs.com" in url:
        return "dashscope"
    if "bigmodel.cn" in url:
        return "zhipu"
    if not url or "api.openai.com" in url:
        return "openai"
    return "custom"


def _migrate_1_to_2(raw: dict[str, Any]) -> dict[str, Any]:
    """旧 provider（一项混合账号/协议/模型）拆为 connection + profile。"""
    migrated = deepcopy(raw)
    old_model = migrated.get("model", {})
    old_providers = old_model.get("providers", {})
    connections: dict[str, Any] = {}
    profiles: dict[str, Any] = {}
    protocol_by_kind: dict[str, WireProtocol] = {
        "ollama": "openai_chat",
        "openai_compatible": "openai_chat",
        "openai_responses": "openai_responses",
        "anthropic": "anthropic_messages",
    }
    for provider_id, provider in old_providers.items():
        kind = provider.get("kind", "openai_compatible")
        protocol = protocol_by_kind.get(kind, "openai_chat")
        base_url = provider.get("base_url")
        endpoints: dict[str, str] = {}
        if base_url:
            endpoints[protocol] = base_url
        elif kind == "ollama":
            endpoints[protocol] = OLLAMA_DEFAULT_BASE_URL
        connection: dict[str, Any] = {
            "preset_id": _infer_preset_id(kind, base_url),
            "display_name": provider.get("display_name", provider_id),
            "endpoints": endpoints,
        }
        if provider.get("key_ref"):
            connection["key_ref"] = provider["key_ref"]
        profile: dict[str, Any] = {
            "connection_id": provider_id,
            "display_name": provider.get("display_name", provider_id),
            "protocol": protocol,
            "model": provider.get("model", ""),
        }
        if provider.get("context_window") is not None:
            profile["context_window"] = provider["context_window"]
        connections[provider_id] = connection
        profiles[provider_id] = profile
    migrated["model"] = {
        "default_profile": old_model.get("default_provider", TRIAL_PROFILE_ID),
        "connections": connections,
        "profiles": profiles,
    }
    return migrated


# config_version N → N+1 的迁移函数注册表；迁移必须幂等且只增不删。
_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {1: _migrate_1_to_2}


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """按迁移链把 raw 升级到当前 CONFIG_VERSION。"""
    version = raw.get("config_version", 1)
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


def _validate_model_references(config: AppConfig) -> None:
    """默认模型与 profile → connection 引用必须完整。"""
    default = config.model.default_profile
    if default != TRIAL_PROFILE_ID and default not in config.model.profiles:
        raise ConfigError(f"default_profile={default!r} 未在 profiles 中定义")
    for profile_id, profile in config.model.profiles.items():
        if profile.connection_id not in config.model.connections:
            raise ConfigError(
                f"profile={profile_id!r} 引用了不存在的 connection={profile.connection_id!r}"
            )


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
        source_version = raw.get("config_version", 1)
        raw = migrate(raw)
        config = AppConfig.model_validate(raw)
        _validate_model_references(config)
        if isinstance(source_version, int) and source_version < CONFIG_VERSION:
            try:
                save_config(path, config)
            except OSError as exc:
                # 内存中的已迁移配置仍可正常运行；避免仅因升级落盘失败就把原文件
                # 当作损坏配置备份并覆盖为默认值。
                logger.warning("配置已迁移但暂时无法落盘，将在下次启动重试：%s", exc)
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
