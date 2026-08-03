"""RunManager —— 对话回合（run）会话管理。

职责：
- runId → asyncio.Task 注册表
- 统一包裹 run.started / run.finished 生命周期事件
- chat.cancel → Task.cancel() → reason="cancelled"
- Agent 异常 → run.error + reason="error"（错误文案可读，功能清单 6.7）
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ..events import (
    EVENT_TYPES,
    ChatSendData,
    ErrorCode,
    ErrorPayload,
    RunErrorData,
    RunFinishedData,
    RunStartedData,
    make_frame,
)
from .service import AgentContext, AgentService

logger = logging.getLogger(__name__)

SendFrame = Callable[[dict[str, Any]], Awaitable[None]]


def _now_ms() -> int:
    return int(time.time() * 1000)


class RunManager:
    """每个 WebSocket 连接持有一个实例（M0 单客户端）。"""

    def __init__(self, agent: AgentService, send_frame: SendFrame) -> None:
        self._agent = agent
        self._send = send_frame
        self._runs: dict[str, asyncio.Task[None]] = {}

    async def start_run(self, data: ChatSendData) -> None:
        existing = self._runs.get(data.run_id)
        if existing and not existing.done():
            logger.warning("重复的 runId，忽略：%s", data.run_id)
            return
        self._runs[data.run_id] = asyncio.create_task(self._run_loop(data))

    async def cancel_run(self, run_id: str) -> None:
        task = self._runs.get(run_id)
        if task and not task.done():
            task.cancel()

    async def _run_loop(self, data: ChatSendData) -> None:
        ctx = AgentContext(run_id=data.run_id, session_id=data.session_id, text=data.text)
        await self._send(
            make_frame(
                EVENT_TYPES["run.started"],
                RunStartedData(run_id=ctx.run_id, session_id=ctx.session_id),
                _now_ms(),
            )
        )

        reason = "complete"
        try:
            async for event_type, payload in self._agent.run(ctx):
                await self._send(make_frame(event_type, payload, _now_ms()))
        except asyncio.CancelledError:
            reason = "cancelled"
        except Exception:
            reason = "error"
            logger.exception("Agent 回合异常：run_id=%s", ctx.run_id)
            with contextlib.suppress(Exception):
                await self._send(
                    make_frame(
                        EVENT_TYPES["run.error"],
                        RunErrorData(
                            run_id=ctx.run_id,
                            error=ErrorPayload(
                                code=ErrorCode.INTERNAL,
                                message="我这边出了点小状况，请再试一次",
                                retryable=True,
                            ),
                        ),
                        _now_ms(),
                    )
                )

        with contextlib.suppress(Exception):
            await self._send(
                make_frame(
                    EVENT_TYPES["run.finished"],
                    RunFinishedData(run_id=ctx.run_id, reason=reason),
                    _now_ms(),
                )
            )
        self._runs.pop(data.run_id, None)
