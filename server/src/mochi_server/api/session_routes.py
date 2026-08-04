"""会话历史 REST 路由（功能清单 4.3 回看面 + 6.2 多轮事实源）。

与 /config 同样只对本机开放（localhost_only）；读多写少，全部委托 SessionStore。
前端经此拉取历史回显，WS 协议（v0.1 冻结）不承载历史查询（ADR-0002 D3）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..events import CamelModel
from ..store import SessionStore
from .security import localhost_only

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"], dependencies=[Depends(localhost_only)])


# ---------------------------------------------------------------------------
# 响应模型（camelCase，与前端约定一致）
# ---------------------------------------------------------------------------


class SessionSummary(CamelModel):
    id: str
    title: str | None = None
    created_at: int
    updated_at: int


class MessageItem(CamelModel):
    role: str
    content: str
    ts: int


# ---------------------------------------------------------------------------
# 装配辅助
# ---------------------------------------------------------------------------


def _store(request: Request) -> SessionStore:
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="会话服务未就绪")
    return store


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.get("")
async def list_sessions(request: Request) -> list[dict]:
    """全部会话（最近活跃倒序）。"""
    return await _store(request).list_sessions()


@router.get("/{session_id}/messages")
async def get_messages(session_id: str, request: Request) -> list[dict]:
    """指定会话的全部消息（时间正序）。空会话返回空列表。"""
    return await _store(request).get_messages(session_id)


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request) -> None:
    """删除会话及其全部消息。幂等：不存在亦返回 204。"""
    deleted = await _store(request).delete_session(session_id)
    logger.info("删除会话：%s（%s）", session_id, "已删除" if deleted else "本不存在")
