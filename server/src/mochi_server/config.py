"""用户配置 schema（规范：docs/specs/config-format.md）。

原则：
- sidecar 是配置的唯一事实源，前端经 RPC 读写，不直接碰文件；
- TOML 存储、pydantic 校验、原子写入（tmp + rename）；
- 敏感信息（API Key）只存 key_ref（系统钥匙串条目名），永不落明文。
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

CONFIG_VERSION = 1

ProviderKind = Literal["ollama", "openai_compatible", "anthropic"]


class GeneralConfig(BaseModel):
    language: Literal["zh-CN", "en"] = "zh-CN"
    launch_at_startup: bool = False
    telemetry: bool = False


class CharacterConfig(BaseModel):
    active_skin: str = "default"


class ModelProviderConfig(BaseModel):
    kind: ProviderKind
    display_name: str
    base_url: str | None = None
    model: str
    key_ref: str | None = None  # 系统钥匙串条目名；ollama 通常无需


class ModelConfig(BaseModel):
    default_provider: str
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
    model: ModelConfig
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)


def load_config(path: Path) -> AppConfig:
    """读取并校验配置文件。

    TODO(M0)：
    - 文件不存在时生成默认配置（含 Ollama 探测结果）；
    - config_version 迁移链（N → N+1 逐步升级）；
    - 校验 model.default_provider 必须存在于 providers。
    """
    with path.open("rb") as f:
        raw = tomllib.load(f)
    return AppConfig.model_validate(raw)


def save_config(path: Path, config: AppConfig) -> None:
    """原子写入配置。

    TODO(M0)：序列化为 TOML（tomli_w）+ tmp 文件 + os.replace 原子替换。
    注意：TOML 注释在往返后不保留，需在规范文档中向用户说明。
    """
    raise NotImplementedError("M0 实现")
