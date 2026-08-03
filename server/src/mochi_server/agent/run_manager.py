"""RunManager —— 对话回合（run）会话管理。

职责：
- runId → asyncio.Task 注册表
- 统一包裹 run.started / run.finished 生命周期事件
- chat.cancel → Task.cancel() → reason="cancelled"
- AgentError（适配层业务错误）→ run.error 透传其 payload（含 hint）
- 未知异常 → run.error + reason="error"（错误文案可读，功能清单 6.7）
- 回合中断（取消/出错）后补发 state.change(idle)，避免角色卡在中间状态
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
    StateChangeData,
    make_frame,
)
from .errors import AgentError
from .service import AgentContext, AgentService

logger = logging.getLogger(__name__)

SendFrame = Callable[[dict[str, Any]], Awaitable[None]]


def _now_ms() -> int:
    return int(time.time() * 1000)


class RunManager:
    """每个 WebSocket 连接持有一个实例（M0 单客户端）。

    agent 参数支持两种形态：
    - AgentService 实例（S1 兼容路径：注入即用）
    - 零参可调用（如 ProviderRegistry.current_agent）：每回合解析，支持模型热切换
    """

    def __init__(
        self, agent: AgentService | Callable[[], AgentService], send_frame: SendFrame
    ) -> None:
        self._agent_source = agent if callable(agent) else lambda: agent
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

    async def _send_run_error(self, run_id: str, error: ErrorPayload) -> None:
        with contextlib.suppress(Exception):
            await self._send(
                make_frame(
                    EVENT_TYPES["run.error"],
                    RunErrorData(run_id=run_id, error=error),
                    _now_ms(),
                )
            )

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
        interrupted = False
        try:
            # 解析在 try 内：构造期错误（缺 Key、未实现的 provider）也走 run.error
            agent = self._agent_source()
            async for event_type, payload in agent.run(ctx):
                await self._send(make_frame(event_type, payload, _now_ms()))
        except asyncio.CancelledError:
            reason = "cancelled"
            interrupted = True
        except AgentError as exc:
            reason = "error"
            interrupted = True
            logger.warning("Agent 业务错误：run_id=%s code=%s", ctx.run_id, exc.payload.code)
            await self._send_run_error(ctx.run_id, exc.payload)
        except Exception:
            reason = "error"
            interrupted = True
            logger.exception("Agent 回合异常：run_id=%s", ctx.run_id)
            await self._send_run_error(
                ctx.run_id,
                ErrorPayload(
                    code=ErrorCode.INTERNAL,
                    message="我这边出了点小状况，请再试一次",
                    retryable=True,
                ),
            )

        if interrupted:
            # 回合未走完（取消/出错）：把角色状态拉回待机，避免卡在 thinking/talking
            with contextlib.suppress(Exception):
                await self._send(
                    make_frame(
                        EVENT_TYPES["state.change"],
                        StateChangeData(state="idle"),
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
