"""配置与模型管理路由（功能清单 7.2 接口面 + 6.3 Key 存储）。

红线：
- Key 只经 POST/PUT body 单向传入，GET 一律只回 key_ref + masked_key；
- DELETE 同步删除钥匙串条目；
- 所有写操作：pydantic 校验 → 原子落盘 → registry 热更新（切换无需重启）。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from ..agent.ollama_probe import probe_ollama
from ..agent.registry import AgentFactory
from ..config import (
    TRIAL_PROFILE_ID,
    AppConfig,
    Language,
    ModelConnectionConfig,
    ModelProfileConfig,
    ResolvedModelTarget,
    WireProtocol,
    save_config,
)
from ..events import CamelModel
from ..model_catalog import catalog_view, get_preset
from ..persona import CATALOG, valid_preset_id
from ..secrets import KeyStore, KeyStoreError
from .security import localhost_only

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(localhost_only)])

_MODEL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


# ---------------------------------------------------------------------------
# 请求/响应模型（camelCase，与前端约定一致）
# ---------------------------------------------------------------------------


class ModelConfigure(CamelModel):
    """测试成功后一次性保存 connection + profile。"""

    profile_id: str
    connection_id: str
    preset_id: str
    connection_name: str
    profile_name: str
    protocol: WireProtocol
    base_url: str | None = None
    model: str
    api_key: str | None = None
    context_window: int | None = Field(default=None, gt=0)


class ModelProfileSummary(CamelModel):
    id: str
    connection_id: str
    preset_id: str
    connection_name: str
    display_name: str
    protocol: WireProtocol
    base_url: str | None = None
    model: str
    context_window: int | None = None
    key_ref: str | None = None
    masked_key: str | None = None
    is_default: bool = False


class ModelTestResult(CamelModel):
    ok: bool
    hint: str | None = None


class DefaultProfileUpdate(CamelModel):
    default_profile: str


class GeneralUpdate(CamelModel):
    """[general] 部分更新（M1-CTX）：仅传入需要变更的字段。"""

    language: Language | None = None
    power_save: bool | None = None


class VoiceUpdate(CamelModel):
    """[voice] 部分更新（M1-S0 托盘静音；S2 TTS 设置）：仅传入需变更字段。"""

    tts_enabled: bool | None = None
    engine: Literal["edge", "local"] | None = None
    voice_id: str | None = None
    volume: float | None = Field(default=None, ge=0.0, le=1.0)
    rate: float | None = Field(default=None, ge=0.5, le=2.0)
    muted: bool | None = None


class VoiceView(CamelModel):
    """[voice] 当前值视图（camelCase 响应）。"""

    tts_enabled: bool
    engine: Literal["edge", "local"]
    voice_id: str
    volume: float
    rate: float
    muted: bool


def _voice_view(config: AppConfig) -> dict:
    return VoiceView.model_validate(config.voice.model_dump()).model_dump(by_alias=True)


class AgentUpdate(CamelModel):
    """[agent] 部分更新：仅传入需变更字段（当前开放 maxReplyChars；

    emotion/cues/attention 为枚举开关，暂无 UI，仍可经 PUT 全量视图后续开放）。
    """

    max_reply_chars: int | None = Field(default=None, ge=50, le=4000)


class AgentView(CamelModel):
    """[agent] 当前值视图（camelCase 响应）。"""

    emotion: str
    cues: str
    attention: str
    max_reply_chars: int


def _agent_view(config: AppConfig) -> dict:
    return AgentView.model_validate(config.agent.model_dump()).model_dump(by_alias=True)


class GeneralView(CamelModel):
    """[general] 当前值视图（camelCase 响应；2.6 省电模式增补）。"""

    language: str
    launch_at_startup: bool
    telemetry: bool
    power_save: bool


def _general_view(config: AppConfig) -> dict:
    return GeneralView.model_validate(config.general.model_dump()).model_dump(by_alias=True)


class PersonaUpdate(CamelModel):
    """[character.persona] 部分更新（6.13 人格系统）：仅传入需变更的字段。

    None = 不变；空串 = 清空该维度选择（恢复默认用全空 PUT）。
    """

    soul_preset: str | None = None
    soul_custom: str | None = Field(default=None, max_length=500)
    personality_preset: str | None = None
    personality_custom: str | None = Field(default=None, max_length=500)
    style_preset: str | None = None
    style_custom: str | None = Field(default=None, max_length=500)


class PersonaView(CamelModel):
    """[character.persona] 当前值视图（camelCase 响应，与 VoiceView 同款）。"""

    soul_preset: str
    soul_custom: str
    personality_preset: str
    personality_custom: str
    style_preset: str
    style_custom: str


def _persona_view(config: AppConfig) -> dict:
    return PersonaView.model_validate(config.character.persona.model_dump()).model_dump(
        by_alias=True
    )


# ---------------------------------------------------------------------------
# 装配辅助
# ---------------------------------------------------------------------------


def _registry(request: Request) -> AgentFactory:
    registry = request.app.state.registry
    if registry is None:
        raise HTTPException(status_code=503, detail="配置服务未就绪")
    return registry


def _config_path(request: Request):
    return request.app.state.config_path


def _profile_summary(
    profile_id: str, config: AppConfig, key_store: KeyStore
) -> ModelProfileSummary:
    profile = config.model.profiles[profile_id]
    connection = config.model.connections[profile.connection_id]
    preset = get_preset(connection.preset_id)
    masked = None
    if connection.key_ref:
        secret = key_store.get_key(profile.connection_id)
        masked = KeyStore.mask(secret) if secret else None
    return ModelProfileSummary(
        id=profile_id,
        connection_id=profile.connection_id,
        preset_id=connection.preset_id,
        connection_name=connection.display_name,
        display_name=profile.display_name,
        protocol=profile.protocol,
        base_url=connection.endpoints.get(profile.protocol)
        or preset.default_endpoints.get(profile.protocol),
        model=profile.model,
        context_window=profile.context_window,
        key_ref=connection.key_ref,
        masked_key=masked,
        is_default=profile_id == config.model.default_profile,
    )


def _apply(registry: AgentFactory, config_path, mutate: Callable[[AppConfig], None]) -> AppConfig:
    """深拷贝 → 变更 → 原子落盘 → registry 热更新。"""
    new_config = registry.config.model_copy(deep=True)
    mutate(new_config)
    save_config(config_path, new_config)
    registry.update_config(new_config)
    return new_config


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.get("")
async def get_config(request: Request) -> dict:
    """脱敏配置视图；配置文件中只含 key_ref，不含明文 Key。"""
    registry = _registry(request)
    cfg = registry.config
    data = cfg.model_dump(mode="json", by_alias=True, exclude_none=True)
    # general 段包一层 camelCase 视图（2.6 powerSave；旧客户端 language 键不变）
    data["general"] = _general_view(cfg)
    return data


@router.get("/model-presets")
async def list_model_presets() -> list[dict]:
    """服务端厂商目录是设置界面的唯一事实源。"""
    from pydantic.alias_generators import to_camel

    return [{to_camel(key): value for key, value in item.items()} for item in catalog_view()]


@router.get("/model-profiles")
async def list_model_profiles(request: Request) -> list[dict]:
    registry = _registry(request)
    cfg = registry.config
    return [
        _profile_summary(profile_id, cfg, registry.key_store).model_dump(
            by_alias=True, exclude_none=True
        )
        for profile_id in cfg.model.profiles
    ]


@router.post("/model-profiles/configure")
async def configure_model_profile(body: ModelConfigure, request: Request) -> dict:
    """用同一份草稿完成真实探测与保存；失败时不留下 Key 或配置。"""
    registry = _registry(request)
    for field_name, value in (
        ("profileId", body.profile_id),
        ("connectionId", body.connection_id),
    ):
        if not _MODEL_ID_PATTERN.fullmatch(value):
            raise HTTPException(
                status_code=422,
                detail=f"{field_name} 仅限小写字母/数字/下划线/连字符，且以字母数字开头",
            )
    if body.profile_id == TRIAL_PROFILE_ID or body.connection_id == TRIAL_PROFILE_ID:
        raise HTTPException(status_code=409, detail="trial 是内置试用模式标识")
    try:
        preset = get_preset(body.preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.protocol not in preset.protocols:
        raise HTTPException(
            status_code=422,
            detail=f"{preset.display_name} 不支持协议 {body.protocol}",
        )
    if not body.model.strip():
        raise HTTPException(status_code=422, detail="请填写模型名称")
    existing_connection = registry.config.model.connections.get(body.connection_id)
    if existing_connection is not None and existing_connection.preset_id != body.preset_id:
        raise HTTPException(status_code=409, detail="已有连接不能更换厂商模板")
    if body.preset_id == "custom" and not body.base_url:
        raise HTTPException(status_code=422, detail="自定义兼容接口必须填写 Base URL")

    effective_key = body.api_key
    if effective_key is None and existing_connection is not None:
        effective_key = registry.key_store.get_key(body.connection_id)
    base_url = body.base_url or (
        existing_connection.endpoints.get(body.protocol) if existing_connection else None
    )
    base_url = base_url or preset.default_endpoints.get(body.protocol)
    target = ResolvedModelTarget(
        connection_id=body.connection_id,
        preset_id=body.preset_id,
        display_name=body.profile_name or body.model,
        protocol=body.protocol,
        base_url=base_url,
        model=body.model.strip(),
        context_window=body.context_window,
    )
    ok, hint = await registry.test_draft(target, api_key=effective_key)
    if not ok:
        return ModelTestResult(ok=False, hint=hint).model_dump(by_alias=True, exclude_none=True)

    old_key = registry.key_store.get_key(body.connection_id)
    key_changed = bool(body.api_key)
    key_ref = existing_connection.key_ref if existing_connection else None
    if body.api_key:
        try:
            key_ref = registry.key_store.set_key(body.connection_id, body.api_key)
        except KeyStoreError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"API Key 存入系统钥匙串失败：{exc}",
            ) from exc

    new_config = registry.config.model_copy(deep=True)
    endpoints = dict(existing_connection.endpoints) if existing_connection else {}
    if body.base_url:
        endpoints[body.protocol] = body.base_url.rstrip("/")
    new_config.model.connections[body.connection_id] = ModelConnectionConfig(
        preset_id=body.preset_id,
        display_name=body.connection_name.strip() or preset.display_name,
        endpoints=endpoints,
        key_ref=key_ref,
    )
    new_config.model.profiles[body.profile_id] = ModelProfileConfig(
        connection_id=body.connection_id,
        display_name=body.profile_name.strip() or body.model.strip(),
        protocol=body.protocol,
        model=body.model.strip(),
        context_window=body.context_window,
    )
    if new_config.model.default_profile == TRIAL_PROFILE_ID:
        new_config.model.default_profile = body.profile_id
    try:
        save_config(_config_path(request), new_config)
    except OSError as exc:
        if key_changed:
            if old_key is None:
                registry.key_store.delete_key(body.connection_id)
            else:
                registry.key_store.set_key(body.connection_id, old_key)
        raise HTTPException(status_code=500, detail="模型配置保存失败") from exc
    registry.update_config(new_config)
    logger.info(
        "模型配置已保存：profile=%s connection=%s protocol=%s",
        body.profile_id,
        body.connection_id,
        body.protocol,
    )
    return {
        "ok": True,
        "profile": _profile_summary(body.profile_id, new_config, registry.key_store).model_dump(
            by_alias=True, exclude_none=True
        ),
    }


@router.delete("/model-profiles/{profile_id}", status_code=204)
async def delete_model_profile(profile_id: str, request: Request) -> None:
    registry = _registry(request)
    if profile_id not in registry.config.model.profiles:
        raise HTTPException(status_code=404, detail=f"模型配置 {profile_id} 不存在")

    def mutate(config: AppConfig) -> None:
        del config.model.profiles[profile_id]
        if config.model.default_profile == profile_id:
            config.model.default_profile = TRIAL_PROFILE_ID

    _apply(registry, _config_path(request), mutate)


@router.delete("/model-connections/{connection_id}", status_code=204)
async def delete_model_connection(connection_id: str, request: Request) -> None:
    registry = _registry(request)
    if connection_id not in registry.config.model.connections:
        raise HTTPException(status_code=404, detail=f"模型连接 {connection_id} 不存在")

    def mutate(config: AppConfig) -> None:
        removed = [
            profile_id
            for profile_id, profile in config.model.profiles.items()
            if profile.connection_id == connection_id
        ]
        for profile_id in removed:
            del config.model.profiles[profile_id]
        if config.model.default_profile in removed:
            config.model.default_profile = TRIAL_PROFILE_ID
        del config.model.connections[connection_id]

    _apply(registry, _config_path(request), mutate)
    registry.key_store.delete_key(connection_id)


@router.put("/model-profiles/{profile_id}/default")
async def set_default_profile(profile_id: str, request: Request) -> dict:
    registry = _registry(request)
    if profile_id != TRIAL_PROFILE_ID and profile_id not in registry.config.model.profiles:
        raise HTTPException(status_code=404, detail=f"模型配置 {profile_id} 不存在")
    new_config = _apply(
        registry,
        _config_path(request),
        lambda config: setattr(config.model, "default_profile", profile_id),
    )
    return {"defaultProfile": new_config.model.default_profile}


@router.put("/model/default")
async def update_default_profile(body: DefaultProfileUpdate, request: Request) -> dict:
    return await set_default_profile(body.default_profile, request)


@router.put("/general")
async def update_general(body: GeneralUpdate, request: Request) -> dict:
    """更新 [general]（界面语言等）：pydantic 校验 → 原子落盘 → 返回最新 general。"""
    registry = _registry(request)

    def mutate(config: AppConfig) -> None:
        if body.language is not None:
            config.general.language = body.language
        if body.power_save is not None:
            config.general.power_save = body.power_save

    new_config = _apply(registry, _config_path(request), mutate)
    logger.info(
        "更新通用设置：language=%s power_save=%s",
        new_config.general.language,
        new_config.general.power_save,
    )
    return _general_view(new_config)


@router.get("/voice")
async def get_voice(request: Request) -> dict:
    """[voice] 当前值（M1-S0：托盘静音读写；S2 TTS 设置面板复用）。"""
    registry = _registry(request)
    return _voice_view(registry.config)


@router.put("/voice")
async def update_voice(body: VoiceUpdate, request: Request) -> dict:
    """更新 [voice]：pydantic 校验 → 原子落盘 → 返回最新 voice。"""
    registry = _registry(request)

    def mutate(config: AppConfig) -> None:
        if body.tts_enabled is not None:
            config.voice.tts_enabled = body.tts_enabled
        if body.engine is not None:
            config.voice.engine = body.engine
        if body.voice_id is not None:
            config.voice.voice_id = body.voice_id
        if body.volume is not None:
            config.voice.volume = body.volume
        if body.rate is not None:
            config.voice.rate = body.rate
        if body.muted is not None:
            config.voice.muted = body.muted

    new_config = _apply(registry, _config_path(request), mutate)
    logger.info(
        "更新语音设置：muted=%s tts_enabled=%s",
        new_config.voice.muted,
        new_config.voice.tts_enabled,
    )
    return _voice_view(new_config)


@router.get("/agent")
async def get_agent(request: Request) -> dict:
    """[agent] 当前值（认知行为：情绪/表演节拍/注意力/回复长度上限）。"""
    registry = _registry(request)
    return _agent_view(registry.config)


@router.put("/agent")
async def update_agent(body: AgentUpdate, request: Request) -> dict:
    """更新 [agent]：pydantic 校验 → 原子落盘 → 返回最新视图。

    max_reply_chars 下一回合生效（agent 按 registry 版本号重建，与模型切换同机制）。
    """
    registry = _registry(request)

    def mutate(config: AppConfig) -> None:
        if body.max_reply_chars is not None:
            config.agent.max_reply_chars = body.max_reply_chars

    new_config = _apply(registry, _config_path(request), mutate)
    logger.info("更新认知行为设置：max_reply_chars=%s", new_config.agent.max_reply_chars)
    return _agent_view(new_config)


@router.get("/persona")
async def get_persona(request: Request) -> dict:
    """人格当前配置 + 内置预设目录（6.13）：一次拉齐供角色 tab 渲染。"""
    registry = _registry(request)
    return {"current": _persona_view(registry.config), "presets": CATALOG.view()}


@router.put("/persona")
async def update_persona(body: PersonaUpdate, request: Request) -> dict:
    """更新 [character.persona]：preset 合法性校验 → 原子落盘 → registry 热更新。

    下一回合 agent 重建即生效（无需重启，与模型切换同机制）。
    """
    registry = _registry(request)
    for dimension, preset_id in (
        ("soul", body.soul_preset),
        ("personality", body.personality_preset),
        ("style", body.style_preset),
    ):
        if preset_id is not None and not valid_preset_id(dimension, preset_id):
            raise HTTPException(status_code=422, detail=f"{dimension} 预设不存在：{preset_id}")

    def mutate(config: AppConfig) -> None:
        persona = config.character.persona
        # model_dump 默认 snake_case 字段名，与 PersonaConfig 一致；exclude_none 保持部分更新语义
        for field_name, value in body.model_dump(exclude_none=True).items():
            setattr(persona, field_name, value)

    new_config = _apply(registry, _config_path(request), mutate)
    logger.info("更新人格设置：persona 已落盘并热生效")
    return _persona_view(new_config)


class CharacterView(CamelModel):
    """[character] 当前值视图（仅暴露 activeSkin；persona 有专属端点）。"""

    active_skin: str


class CharacterUpdate(CamelModel):
    active_skin: str | None = None


class SettingsTransfer(CamelModel):
    """可迁移的设置；接受旧文件的 snake_case，不含模型连接与钥匙串引用。"""

    format: Literal["mochi-settings"] | None = None
    version: Literal[1] | None = None
    exported_at: str | None = None
    general: GeneralUpdate | None = None
    character: CharacterUpdate | None = None
    voice: VoiceUpdate | None = None
    agent: AgentUpdate | None = None
    persona: PersonaUpdate | None = None


@router.get("/export")
async def export_settings(request: Request) -> dict:
    config = _registry(request).config
    return SettingsTransfer(
        format="mochi-settings",
        version=1,
        exported_at=datetime.now(UTC).isoformat(),
        general=GeneralUpdate(
            language=config.general.language, power_save=config.general.power_save
        ),
        character=CharacterUpdate(active_skin=config.character.active_skin),
        voice=VoiceUpdate.model_validate(config.voice.model_dump()),
        agent=AgentUpdate(max_reply_chars=config.agent.max_reply_chars),
        persona=PersonaUpdate.model_validate(config.character.persona.model_dump()),
    ).model_dump(by_alias=True, exclude_none=True)


@router.post("/import")
async def import_settings(body: SettingsTransfer, request: Request) -> dict:
    """整份文件校验后一次原子保存，错误文件不会留下半份设置。"""
    sections = {
        name: section.model_dump(exclude_none=True)
        for name in ("general", "character", "voice", "agent", "persona")
        if (section := getattr(body, name)) is not None
    }
    if not any(sections.values()):
        raise HTTPException(status_code=422, detail="文件未包含可导入的 Mochi 设置")
    skin_id = sections.get("character", {}).get("active_skin")
    if skin_id:
        skins = request.app.state.skin_registry
        if skins is None or not skins.has(skin_id):
            raise HTTPException(status_code=422, detail=f"请先在装扮管理中导入角色：{skin_id}")
    for dimension in ("soul", "personality", "style"):
        preset_id = sections.get("persona", {}).get(f"{dimension}_preset")
        if preset_id is not None and not valid_preset_id(dimension, preset_id):
            raise HTTPException(status_code=422, detail=f"{dimension} 预设不存在：{preset_id}")

    def mutate(config: AppConfig) -> None:
        for name, values in sections.items():
            target = config.character.persona if name == "persona" else getattr(config, name)
            for field, value in values.items():
                setattr(target, field, value)

    registry = _registry(request)
    config = _apply(registry, _config_path(request), mutate)
    return {
        "general": _general_view(config),
        "character": _character_view(config),
        "voice": _voice_view(config),
    }


def _character_view(config: AppConfig) -> dict:
    return CharacterView(active_skin=config.character.active_skin).model_dump(by_alias=True)


@router.get("/character")
async def get_character(request: Request) -> dict:
    registry = _registry(request)
    return _character_view(registry.config)


@router.put("/character")
async def update_character(body: CharacterUpdate, request: Request) -> dict:
    """更新 [character.active_skin]（3.3 一键换肤）：皮肤须存在于注册表，否则 422。"""
    registry = _registry(request)
    if body.active_skin:
        skin_registry = request.app.state.skin_registry
        if skin_registry is None or not skin_registry.has(body.active_skin):
            raise HTTPException(status_code=422, detail=f"皮肤不存在：{body.active_skin}")

    def mutate(config: AppConfig) -> None:
        if body.active_skin is not None:
            config.character.active_skin = body.active_skin

    new_config = _apply(registry, _config_path(request), mutate)
    logger.info("更新角色设置：active_skin=%s", new_config.character.active_skin)
    return _character_view(new_config)


@router.post("/model-profiles/{profile_id}/test")
async def test_model_profile(profile_id: str, request: Request) -> dict:
    registry = _registry(request)
    ok, hint = await registry.test_profile(profile_id)
    return ModelTestResult(ok=ok, hint=hint).model_dump(by_alias=True, exclude_none=True)


@router.get("/models/ollama-status")
async def ollama_status(request: Request) -> dict:
    registry = _registry(request)
    ollama_connection = next(
        (
            connection
            for connection in registry.config.model.connections.values()
            if connection.preset_id == "ollama"
        ),
        None,
    )
    base_url = ollama_connection.endpoints.get("openai_chat") if ollama_connection else None
    result = await probe_ollama(base_url) if base_url else await probe_ollama()
    return result.model_dump(by_alias=True, exclude_none=True)
