"""皮肤 REST 端点（M1-S1，功能清单 3.2/3.3/3.5）。

- ``GET /skins``：注册表列表（内置 + 用户），含双轨 resourceBaseUrl；
- ``DELETE /skins/{id}`：用户皮肤可删（内置 403），删 active 自动回退 default；
- ``GET /user-skins/{id}/{path}``：用户皮肤资源分发——普通路由 + FileResponse，
  继承应用级 CORS 中间件（ADR-0006 D2）；路径穿越校验。

导入端点（POST /skins/import）见 importer 提交。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from ..config import AppConfig
from ..paths import get_skins_dir
from ..skin.registry import SkinRegistry
from .config_routes import _apply, _config_path, _registry
from .security import localhost_only

logger = logging.getLogger(__name__)

router = APIRouter(tags=["skins"], dependencies=[Depends(localhost_only)])


def _skin_registry(request: Request) -> SkinRegistry:
    registry = request.app.state.skin_registry
    if registry is None:
        raise HTTPException(status_code=503, detail="皮肤服务未就绪")
    return registry


@router.get("/skins")
async def list_skins(request: Request) -> list[dict]:
    """皮肤列表：内置（相对 base URL）+ 用户（绝对 base URL）。"""
    registry = _skin_registry(request)
    return [s.model_dump(by_alias=True, exclude_none=True) for s in registry.list_all()]


@router.delete("/skins/{skin_id}", status_code=204)
async def delete_skin(skin_id: str, request: Request) -> None:
    """删除用户皮肤；内置 403。若正是 active_skin → 回退 default 并落盘。"""
    skin_registry = _skin_registry(request)
    if skin_registry.is_builtin(skin_id):
        raise HTTPException(status_code=403, detail="内置皮肤不可删除")
    if not skin_registry.delete(skin_id):
        raise HTTPException(status_code=404, detail=f"皮肤 {skin_id} 不存在")

    provider_registry = _registry(request)
    if provider_registry.config.character.active_skin == skin_id:

        def mutate(config: AppConfig) -> None:
            config.character.active_skin = "default"

        _apply(provider_registry, _config_path(request), mutate)
        logger.info("删除的 %s 正是当前皮肤，已回退 default", skin_id)
    logger.info("删除皮肤：%s", skin_id)


@router.get("/user-skins/{skin_id}/{path:path}")
async def get_user_skin_file(skin_id: str, path: str, request: Request) -> FileResponse:
    """用户皮肤静态资源（CORS 继承应用级中间件）。路径穿越 → 404。"""
    _skin_registry(request)
    base = get_skins_dir().resolve()
    target = (base / skin_id / path).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise HTTPException(status_code=404, detail="资源不存在")
    return FileResponse(target)
