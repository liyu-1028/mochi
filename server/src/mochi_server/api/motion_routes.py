"""动作库 REST 端点（ADR-0011 P2.7，设置面板「动作管理」）。

- ``GET /motions``：导入动作条目（角色内置 / 用户扩展）；
- ``POST /motions``：导入动作文件（.vrma）+ 元数据；
- ``PATCH /motions/{id}`：修改元数据（label/分类/署名/调度参数/tags/agentSelectable）；
- ``DELETE /motions/{id}``：删除条目与文件；
- ``GET /motion-library/{file}``：动作文件分发（路径穿越 → 404）。

动画内容（骨骼/轨道合法性）由前端加载时校验——服务端只验结构与扩展，
与皮肤「服务端只验结构」同口径。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from ..motion.library import (
    MOTION_FILE_EXTENSIONS,
    MOTION_FILE_MAX_BYTES,
    ConflictError,
    MotionEntry,
    MotionLibrary,
)
from .security import localhost_only

logger = logging.getLogger(__name__)

router = APIRouter(tags=["motions"], dependencies=[Depends(localhost_only)])


def _library(request: Request) -> MotionLibrary:
    library = getattr(request.app.state, "motion_library", None)
    if library is None:
        raise HTTPException(status_code=503, detail="动作库服务未就绪")
    return library


@router.get("/motions")
async def list_motions(request: Request, skinId: str | None = None) -> list[dict]:
    return [e.model_dump(by_alias=True) for e in _library(request).list_all(skinId)]


@router.post("/motions", status_code=201)
async def import_motion(
    request: Request,
    file: UploadFile,
    id: str = Form(...),
    label: str = Form(...),
    kind: str = Form("oneshot"),
    durationMs: int = Form(2000),
    priority: int = Form(50),
    cooldownMs: int = Form(0),
    agentSelectable: bool = Form(False),
    tags: str = Form(""),
    credit: str = Form(""),
    category: str = Form("custom"),
) -> dict:
    """导入动作：multipart（file + 元数据）。id 冲突 409，畸形元数据 422。"""
    library = _library(request)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in MOTION_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的动作文件格式 {suffix or '(无扩展名)'}（合法：{sorted(MOTION_FILE_EXTENSIONS)}）",
        )
    content = await file.read()
    if len(content) > MOTION_FILE_MAX_BYTES:
        raise HTTPException(status_code=422, detail="动作文件超过 50MB 上限")
    if not content:
        raise HTTPException(status_code=422, detail="动作文件为空")

    try:
        entry = MotionEntry.model_validate(
            {
                "id": id,
                "label": label,
                "kind": kind,
                "durationMs": durationMs,
                "priority": priority,
                "cooldownMs": cooldownMs,
                "agentSelectable": agentSelectable,
                "tags": [t for t in tags.split(",") if t],
                "credit": credit,
                "category": category,
                "file": f"placeholder{suffix}",
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        stored = library.create(entry, content)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return stored.model_dump(by_alias=True)


@router.patch("/motions/{motion_id}", status_code=200)
async def update_motion(motion_id: str, request: Request, patch: dict) -> dict:
    """修改元数据。id/file 不可改（文件名与 id 绑定）。"""
    library = _library(request)
    if "id" in patch and patch["id"] != motion_id:
        raise HTTPException(status_code=422, detail="动作 id 不可修改（删除后重新导入）")
    if "file" in patch:
        raise HTTPException(status_code=422, detail="动作文件不可直接修改（删除后重新导入）")
    try:
        updated = library.update(motion_id, patch)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"动作 {motion_id} 不存在") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return updated.model_dump(by_alias=True)


@router.delete("/motions/{motion_id}", status_code=204)
async def delete_motion(motion_id: str, request: Request) -> None:
    try:
        deleted = _library(request).delete(motion_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"动作 {motion_id} 不存在")


@router.get("/motion-library/{file_path:path}")
async def get_motion_file(file_path: str, request: Request) -> FileResponse:
    """动作文件分发（CORS 继承应用级中间件）。路径穿越 → 404。"""
    library = _library(request)
    entry = next((e for e in library.list_all() if e.file == file_path), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    target = library.file_path(entry)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="资源不存在")
    return FileResponse(target)
