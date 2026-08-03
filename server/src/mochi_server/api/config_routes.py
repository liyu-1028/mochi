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

from fastapi import APIRouter, Depends, HTTPException, Request

from ..agent.ollama_probe import probe_ollama
from ..agent.registry import ProviderRegistry
from ..config import (
    TRIAL_PROVIDER_ID,
    AppConfig,
    ModelProviderConfig,
    ProviderKind,
    save_config,
)
from ..events import CamelModel
from ..secrets import KeyStore, key_ref_for
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
        key_ref = registry.key_store.set_key(provider_id, body.api_key)

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
        registry.key_store.set_key(provider_id, body.api_key)

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
