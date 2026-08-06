"""配置与模型提供方管理路由（功能清单 7.2 接口面 + 6.3 Key 存储）。

红线：
- Key 只经 POST/PUT body 单向传入，GET 一律只回 key_ref + masked_key；
- DELETE 同步删除钥匙串条目；
- 所有写操作：pydantic 校验 → 原子落盘 → registry 热更新（切换无需重启）。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from ..agent.ollama_probe import probe_ollama
from ..agent.registry import ProviderRegistry
from ..config import (
    TRIAL_PROVIDER_ID,
    AppConfig,
    Language,
    ModelProviderConfig,
    ProviderKind,
    save_config,
)
from ..events import CamelModel
from ..persona import CATALOG, valid_preset_id
from ..secrets import KeyStore, KeyStoreError, key_ref_for
from .security import localhost_only

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(localhost_only)])

_PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


# ---------------------------------------------------------------------------
# 请求/响应模型（camelCase，与前端约定一致）
# ---------------------------------------------------------------------------


class ProviderCreate(CamelModel):
    id: str
    kind: ProviderKind
    display_name: str
    base_url: str | None = None
    model: str
    api_key: str | None = None  # 单向传入：落钥匙串后永不回显


class ProviderUpdate(CamelModel):
    display_name: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


class ProviderSummary(CamelModel):
    id: str
    kind: ProviderKind
    display_name: str
    base_url: str | None = None
    model: str
    key_ref: str | None = None
    masked_key: str | None = None
    is_default: bool = False


class ProviderTestResult(CamelModel):
    ok: bool
    hint: str | None = None


class DefaultProviderUpdate(CamelModel):
    default_provider: str


class GeneralUpdate(CamelModel):
    """[general] 部分更新（M1-CTX）：仅传入需要变更的字段。"""

    language: Language | None = None


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


def _registry(request: Request) -> ProviderRegistry:
    registry = request.app.state.registry
    if registry is None:
        raise HTTPException(status_code=503, detail="配置服务未就绪")
    return registry


def _config_path(request: Request):
    return request.app.state.config_path


def _summary(provider_id: str, cfg, default_provider: str, key_store: KeyStore) -> ProviderSummary:
    masked = None
    if cfg.key_ref:
        secret = key_store.get_key(provider_id)
        masked = KeyStore.mask(secret) if secret else None
    return ProviderSummary(
        id=provider_id,
        kind=cfg.kind,
        display_name=cfg.display_name,
        base_url=cfg.base_url,
        model=cfg.model,
        key_ref=cfg.key_ref,
        masked_key=masked,
        is_default=provider_id == default_provider,
    )


def _apply(
    registry: ProviderRegistry, config_path, mutate: Callable[[AppConfig], None]
) -> AppConfig:
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
    """脱敏配置视图：providers 只含 key_ref + masked_key。"""
    registry = _registry(request)
    cfg = registry.config
    data = cfg.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["model"]["providers"] = [
        _summary(pid, pcfg, cfg.model.default_provider, registry.key_store).model_dump(
            by_alias=True, exclude_none=True
        )
        for pid, pcfg in cfg.model.providers.items()
    ]
    return data


@router.get("/providers")
async def list_providers(request: Request) -> list[dict]:
    registry = _registry(request)
    cfg = registry.config
    return [
        _summary(pid, pcfg, cfg.model.default_provider, registry.key_store).model_dump(
            by_alias=True, exclude_none=True
        )
        for pid, pcfg in cfg.model.providers.items()
    ]


@router.post("/providers", status_code=201)
async def create_provider(body: ProviderCreate, request: Request) -> dict:
    registry = _registry(request)
    provider_id = body.id
    if not _PROVIDER_ID_PATTERN.match(provider_id):
        raise HTTPException(
            status_code=422, detail="provider id 仅限小写字母/数字/下划线/连字符，且以字母数字开头"
        )
    if provider_id == TRIAL_PROVIDER_ID or provider_id in registry.config.model.providers:
        raise HTTPException(status_code=409, detail=f"提供方 {provider_id} 已存在")

    key_ref = None
    if body.api_key:
        try:
            key_ref = registry.key_store.set_key(provider_id, body.api_key)
        except KeyStoreError as exc:
            # 钥匙串写入失败：返回可读错误（经正常响应路径，带 CORS 头），
            # 避免未处理异常 → 500 无 CORS 头 → 前端表现为 "Load failed"
            raise HTTPException(
                status_code=500,
                detail=f"API Key 存入系统钥匙串失败：{exc}",
            ) from exc

    def mutate(config: AppConfig) -> None:
        config.model.providers[provider_id] = ModelProviderConfig(
            kind=body.kind,
            display_name=body.display_name,
            base_url=body.base_url,
            model=body.model,
            key_ref=key_ref,
        )

    new_config = _apply(registry, _config_path(request), mutate)
    logger.info("新增提供方：%s（kind=%s）", provider_id, body.kind)
    return _summary(
        provider_id,
        new_config.model.providers[provider_id],
        new_config.model.default_provider,
        registry.key_store,
    ).model_dump(by_alias=True, exclude_none=True)


@router.put("/providers/{provider_id}")
async def update_provider(provider_id: str, body: ProviderUpdate, request: Request) -> dict:
    registry = _registry(request)
    existing = registry.config.model.providers.get(provider_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"提供方 {provider_id} 不存在")

    if body.api_key:
        try:
            registry.key_store.set_key(provider_id, body.api_key)
        except KeyStoreError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"API Key 存入系统钥匙串失败：{exc}",
            ) from exc

    def mutate(config: AppConfig) -> None:
        cfg = config.model.providers[provider_id]
        if body.display_name is not None:
            cfg.display_name = body.display_name
        if body.base_url is not None:
            cfg.base_url = body.base_url
        if body.model is not None:
            cfg.model = body.model
        if body.api_key:
            cfg.key_ref = key_ref_for(provider_id)

    new_config = _apply(registry, _config_path(request), mutate)
    return _summary(
        provider_id,
        new_config.model.providers[provider_id],
        new_config.model.default_provider,
        registry.key_store,
    ).model_dump(by_alias=True, exclude_none=True)


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: str, request: Request) -> None:
    registry = _registry(request)
    if provider_id not in registry.config.model.providers:
        raise HTTPException(status_code=404, detail=f"提供方 {provider_id} 不存在")

    def mutate(config: AppConfig) -> None:
        del config.model.providers[provider_id]
        if config.model.default_provider == provider_id:
            config.model.default_provider = TRIAL_PROVIDER_ID

    _apply(registry, _config_path(request), mutate)
    registry.key_store.delete_key(provider_id)
    logger.info("删除提供方：%s", provider_id)


@router.put("/providers/{provider_id}/default")
async def set_default_provider(provider_id: str, request: Request) -> dict:
    registry = _registry(request)
    if provider_id != TRIAL_PROVIDER_ID and provider_id not in registry.config.model.providers:
        raise HTTPException(status_code=404, detail=f"提供方 {provider_id} 不存在")

    new_config = _apply(
        registry,
        _config_path(request),
        lambda config: setattr(config.model, "default_provider", provider_id),
    )
    return {"defaultProvider": new_config.model.default_provider}


@router.put("/model/default")
async def update_default_provider(body: DefaultProviderUpdate, request: Request) -> dict:
    registry = _registry(request)
    target = body.default_provider
    if target != TRIAL_PROVIDER_ID and target not in registry.config.model.providers:
        raise HTTPException(status_code=404, detail=f"提供方 {target} 不存在")
    new_config = _apply(
        registry,
        _config_path(request),
        lambda config: setattr(config.model, "default_provider", target),
    )
    return {"defaultProvider": new_config.model.default_provider}


@router.put("/general")
async def update_general(body: GeneralUpdate, request: Request) -> dict:
    """更新 [general]（界面语言等）：pydantic 校验 → 原子落盘 → 返回最新 general。"""
    registry = _registry(request)

    def mutate(config: AppConfig) -> None:
        if body.language is not None:
            config.general.language = body.language

    new_config = _apply(registry, _config_path(request), mutate)
    logger.info("更新通用设置：language=%s", new_config.general.language)
    return new_config.general.model_dump(mode="json", by_alias=True)


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
    if body.active_skin is not None:
        skin_registry = request.app.state.skin_registry
        if skin_registry is None or not skin_registry.has(body.active_skin):
            raise HTTPException(status_code=422, detail=f"皮肤不存在：{body.active_skin}")

    def mutate(config: AppConfig) -> None:
        if body.active_skin is not None:
            config.character.active_skin = body.active_skin

    new_config = _apply(registry, _config_path(request), mutate)
    logger.info("更新角色设置：active_skin=%s", new_config.character.active_skin)
    return _character_view(new_config)


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: str, request: Request) -> dict:
    registry = _registry(request)
    ok, hint = await registry.test_provider(provider_id)
    return ProviderTestResult(ok=ok, hint=hint).model_dump(by_alias=True, exclude_none=True)


@router.get("/providers/ollama-status")
async def ollama_status(request: Request) -> dict:
    registry = _registry(request)
    ollama_cfg = next(
        (p for p in registry.config.model.providers.values() if p.kind == "ollama"), None
    )
    base_url = ollama_cfg.base_url if ollama_cfg and ollama_cfg.base_url else None
    result = await probe_ollama(base_url) if base_url else await probe_ollama()
    return result.model_dump(by_alias=True, exclude_none=True)
