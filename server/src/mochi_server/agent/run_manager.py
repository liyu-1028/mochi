"""RunManager —— 对话回合（run）会话管理。

职责：
- runId → asyncio.Task 注册表
- 统一包裹 run.started / run.finished 生命周期事件
- chat.cancel → Task.cancel() → reason="cancelled" → state.change(idle)
- chat.interrupt → 打断播报（协议 §4，功能清单 5.3）→ reason="interrupted"；
  S0 无 TTS 时与 cancel 同为终止回合，仅 reason 区分语义，
  S2 接入 TTS 后扩展为「停播但保留内容」的真实差异
- AgentError（适配层业务错误）→ run.error 透传其 payload（含 hint）
- 未知异常 → run.error + reason="error"（错误文案可读，功能清单 6.7）
- 出错回合发 state.change(error)（功能清单 2.2 的 error 状态），
  延迟回 idle（新回合开始时取消恢复任务，避免与 thinking 冲突）
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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

#: 补发钩子预算（2.5）：分类调用自身 2s + 余量，超时静默丢弃
_POST_RUN_TIMEOUT_S = 3.0

SendFrame = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(slots=True)
class ProactiveStart:
    """主动回合输入（M-D）：引擎意图 → proactive run（无用户输入）。

    text 为触发指令（引擎生成的现场上下文）：发给 LLM 但不落盘为 user
    message（D4 记忆边界，见 LLMAgentService._persist_assistant_only）。
    """

    run_id: str
    session_id: str
    intent_id: str
    text: str


def _now_ms() -> int:
    return int(time.time() * 1000)


class RunManager:
    """每个 WebSocket 连接持有一个实例（M0 单客户端）。

    agent 参数支持两种形态：
    - AgentService 实例（S1 兼容路径：注入即用）
    - 零参可调用（如 AgentFactory.current_agent）：每回合解析，支持模型热切换
    """

    def __init__(
        self,
        agent: AgentService | Callable[[], AgentService],
        send_frame: SendFrame,
        *,
        error_recovery_delay_s: float = 3.0,
    ) -> None:
        self._agent_source = agent if callable(agent) else lambda: agent
        self._send = send_frame
        self._runs: dict[str, asyncio.Task[None]] = {}
        # 被 interrupt（而非 cancel）终止的 runId：CancelledError 无负载，
        # 经此集合把「打断播报」的语义传递到 run.finished 的 reason
        self._interrupted: set[str] = set()
        # error 状态停留时长：足够用户看到出错表情，又不至于卡住（2.2）
        self._error_recovery_delay_s = error_recovery_delay_s
        self._error_recovery_task: asyncio.Task[None] | None = None
        # 注意力协调器（M-D，可选）：run 活跃/用户消息通知 + proactive 收口记账
        self._coordinator: object | None = None
        # 协程通知的后台任务登记（防 GC 中途回收）
        self._attention_tasks: set[asyncio.Task[None]] = set()

    @property
    def has_active_runs(self) -> bool:
        """是否有进行中的回合（休眠判定用，见 main.py ws_endpoint）。"""
        return any(not task.done() for task in self._runs.values())

    async def start_run(self, data: ChatSendData) -> None:
        existing = self._runs.get(data.run_id)
        if existing and not existing.done():
            logger.warning("重复的 runId，忽略：%s", data.run_id)
            return
        self._cancel_error_recovery()  # 新回合开始，error 表情让位给 thinking
        self._notify_attention(lambda c: c.notify_user_message())  # 用户消息（M-D）
        self._runs[data.run_id] = asyncio.create_task(self._run_loop(data))

    async def start_proactive_run(self, start: ProactiveStart) -> None:
        """主动回合（M-D）：引擎意图触发；与用户回合共用生命周期包裹。"""
        existing = self._runs.get(start.run_id)
        if existing and not existing.done():
            logger.warning("重复的主动 runId，忽略：%s", start.run_id)
            return
        self._cancel_error_recovery()
        self._notify_attention(lambda c: c.notify_run_active(True))
        self._runs[start.run_id] = asyncio.create_task(self._run_loop(start))

    def attach_coordinator(self, coordinator: object) -> None:
        """挂载注意力协调器（M-D）：未挂载时行为与 M-C 结束点一致。"""
        self._coordinator = coordinator

    def _sniff_tool_event(
        self, event_type: str, payload: Any, timings: dict[str, tuple[str, int]]
    ) -> None:
        """从事件流嗅探工具生命周期 → 注意力协调器（M-D D3 服务端信号源）。

        只读不改协议流：start 记 (name, ts)，end 报时长与成败；denied 是
        用户主动拒绝（模型自行善后），不计失败。通知异步收敛、不阻断回合。
        """
        if self._coordinator is None:
            return
        try:
            if event_type == "tool.call.start":
                timings[payload.tool_call_id] = (payload.name, _now_ms())
            elif event_type == "tool.call.end":
                entry = timings.pop(payload.tool_call_id, None)
                if entry is None:
                    return
                name, started = entry
                status = getattr(payload, "status", "success")
                if status == "denied":
                    return
                duration = _now_ms() - started
                succeeded = status == "success"
                self._notify_attention(
                    lambda c, n=name, ok=succeeded, d=duration: c.handle_tool_end(n, ok, d)
                )
        except AttributeError:
            # 负载形态异常（非工具事件模型）：不影响回合
            return

    def _notify_attention(self, method: Callable[[object], Any]) -> None:
        """通知协调器；协程返回值调度为后台任务（fire-and-forget，异常收敛）。"""
        if self._coordinator is None:
            return
        try:
            result = method(self._coordinator)
        except Exception:
            logger.exception("注意力协调器通知失败（忽略）")
            return
        if asyncio.iscoroutine(result):
            task = asyncio.create_task(result)
            self._attention_tasks.add(task)
            task.add_done_callback(self._attention_tasks.discard)

    async def cancel_run(self, run_id: str) -> None:
        task = self._runs.get(run_id)
        if task and not task.done():
            task.cancel()

    async def interrupt_run(self, run_id: str) -> None:
        """打断播报（协议 §4）：回合以 reason="interrupted" 结束，已生成内容保留。

        S0 无 TTS，行为与 cancel 同为终止回合；S2 接入语音后在此扩展
        「停止播报、保留内容」的真实差异（5.3 barge-in）。
        """
        task = self._runs.get(run_id)
        if task and not task.done():
            self._interrupted.add(run_id)
            task.cancel()

    async def _send_state(self, state: str) -> None:
        with contextlib.suppress(Exception):
            await self._send(
                make_frame(
                    EVENT_TYPES["state.change"],
                    StateChangeData(state=state),
                    _now_ms(),
                )
            )

    def _cancel_error_recovery(self) -> None:
        if self._error_recovery_task is not None and not self._error_recovery_task.done():
            self._error_recovery_task.cancel()
        self._error_recovery_task = None

    def _schedule_error_recovery(self) -> None:
        """延迟把角色从 error 拉回 idle；单槽，重复出错只保留最新恢复任务。"""
        self._cancel_error_recovery()

        async def _recover() -> None:
            await asyncio.sleep(self._error_recovery_delay_s)
            await self._send_state("idle")

        self._error_recovery_task = asyncio.create_task(_recover())

    async def _send_run_error(self, run_id: str, error: ErrorPayload) -> None:
        with contextlib.suppress(Exception):
            await self._send(
                make_frame(
                    EVENT_TYPES["run.error"],
                    RunErrorData(run_id=run_id, error=error),
                    _now_ms(),
                )
            )

    async def _run_loop(self, data: ChatSendData | ProactiveStart) -> None:
        if isinstance(data, ProactiveStart):
            ctx = AgentContext(
                run_id=data.run_id,
                session_id=data.session_id,
                text=data.text,
                source="proactive",
                intent_id=data.intent_id,
            )
        else:
            ctx = AgentContext(run_id=data.run_id, session_id=data.session_id, text=data.text)
        await self._send(
            make_frame(
                EVENT_TYPES["run.started"],
                RunStartedData(
                    run_id=ctx.run_id,
                    session_id=ctx.session_id,
                    source=ctx.source,
                    intent_id=ctx.intent_id,
                ),
                _now_ms(),
            )
        )

        reason = "complete"
        agent: AgentService | None = None
        # 工具计时（M-D D3）：tool_call_id → (name, 开始时刻)，收口时报注意力
        tool_timings: dict[str, tuple[str, int]] = {}
        try:
            # 解析在 try 内：构造期错误（缺 Key、未实现的 provider）也走 run.error
            agent = self._agent_source()
            async for event_type, payload in agent.run(ctx):
                self._sniff_tool_event(event_type, payload, tool_timings)
                await self._send(make_frame(event_type, payload, _now_ms()))
        except asyncio.CancelledError:
            # 用户主动停止：不算错误，直接回待机（2.2：error 状态只留给真出错）
            # interrupt（打断播报）与 cancel（停止生成）以 reason 区分语义
            reason = "interrupted" if ctx.run_id in self._interrupted else "cancelled"
            await self._send_state("idle")
        except AgentError as exc:
            reason = "error"
            logger.warning("Agent 业务错误：run_id=%s code=%s", ctx.run_id, exc.payload.code)
            await self._send_run_error(ctx.run_id, exc.payload)
            await self._send_state("error")
            self._schedule_error_recovery()
        except Exception:
            reason = "error"
            logger.exception("Agent 回合异常：run_id=%s", ctx.run_id)
            await self._send_run_error(
                ctx.run_id,
                ErrorPayload(
                    code=ErrorCode.INTERNAL,
                    message="我这边出了点小状况，请再试一次",
                    retryable=True,
                ),
            )
            await self._send_state("error")
            self._schedule_error_recovery()

        with contextlib.suppress(Exception):
            await self._send(
                make_frame(
                    EVENT_TYPES["run.finished"],
                    RunFinishedData(run_id=ctx.run_id, reason=reason),
                    _now_ms(),
                )
            )

        # 情绪后置补发（2.5，ADR-0009）：run.finished 之后送达，不阻塞回合收口；
        # 取消/出错回合不补发；钩子自身带超时兑底，异常不外溢
        if reason == "complete" and agent is not None:
            with contextlib.suppress(Exception):
                for event_type, payload in await asyncio.wait_for(
                    agent.post_run_events(ctx), timeout=_POST_RUN_TIMEOUT_S
                ):
                    await self._send(make_frame(event_type, payload, _now_ms()))

        self._notify_attention(lambda c: c.notify_run_active(False))
        if isinstance(data, ProactiveStart):
            self._notify_attention(lambda c: c.on_run_finished(reason))  # type: ignore[attr-defined]
        self._runs.pop(data.run_id, None)
        self._interrupted.discard(data.run_id)
