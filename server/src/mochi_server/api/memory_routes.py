"""记忆管理 REST 路由（M1-S3，功能清单 6.4）：查看/编辑/删除/清空。

用户隐私可控是验收红线：任一条记忆可查看/编辑/删除，全部可一键清空。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..events import CamelModel
from ..store import SessionStore
from .security import localhost_only

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memories", tags=["memories"], dependencies=[Depends(localhost_only)])


# ---------------------------------------------------------------------------
# 响应模型
# ---------------------------------------------------------------------------


class MemoryItem(CamelModel):
    id: str
    category: str
    content: str
    source: str
    created_at: int
    updated_at: int


class MemoryUpdateBody(BaseModel):
    content: str = Field(min_length=1, max_length=500)


class MemoryCreateBody(BaseModel):
    content: str = Field(min_length=1, max_length=500)
    category: str = Field(default="fact")


# ---------------------------------------------------------------------------
# 装配辅助
# ---------------------------------------------------------------------------


def _store(request: Request) -> SessionStore:
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="记忆服务未就绪")
    return store


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.get("")
async def list_memories(request: Request, category: str | None = None) -> list[dict]:
    """全部记忆（创建倒序）；可选 ?category=fact|preference 过滤。"""
    return await _store(request).list_memories(category=category)


@router.post("", status_code=201)
async def create_memory(request: Request, body: MemoryCreateBody) -> dict:
    """手动添加一条记忆。"""
    import uuid

    memory_id = f"mem-{uuid.uuid4().hex[:12]}"
    cat = body.category if body.category in ("fact", "preference") else "fact"
    return await _store(request).add_memory(memory_id, cat, body.content, source="manual")


@router.put("/{memory_id}")
async def update_memory(memory_id: str, body: MemoryUpdateBody, request: Request) -> dict:
    """编辑记忆内容。"""
    result = await _store(request).update_memory(memory_id, body.content)
    if result is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return result


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(memory_id: str, request: Request) -> None:
    """删除单条记忆。"""
    deleted = await _store(request).delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="记忆不存在")
    logger.info("删除记忆：%s", memory_id)


@router.delete("", status_code=204)
async def clear_all_memories(request: Request) -> None:
    """清空全部记忆。"""
    count = await _store(request).clear_all_memories()
    logger.info("清空全部记忆：%d 条", count)
