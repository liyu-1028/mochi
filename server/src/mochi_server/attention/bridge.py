"""CompanionCoordinator —— ws 连接级的注意力管线组装（M-D D2b）。

职责（把引擎决策接入对话管线，不改变 M-C 结束点行为）：
- ``handle_signal``：协议 CompanionSignalData → 引擎 submit/响应回传；
  通过门控的 speak/ask → 发 companion.intent 事件 + 起 proactive run
  （action_intent 首批无来源，词表预留）；
- run 生命周期回调：run 进行中抑制（notify_run_active）、
  ask 无声过期未回应记账（notify_ask_expired_unanswered）；
- intent_response：later/dismiss/now 三分支（engine 内部状态 + trigger 落盘）；
- D4 记忆边界：触发元数据单独落 triggers 表；proactive 回合不伪造 user
  message（LLMAgentService._persist_assistant_only）。

引擎关闭（``[agent].attention = "off"``）时本协调器不被创建——
companion.signal 命令直接忽略，M-C 结束点行为零变更。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from ..events import (
    EVENT_TYPES,
    CompanionIntentData,
    CompanionSignalData,
    make_frame,
)
from .engine import AttentionEngine
from .intents import Intent, Signal

if TYPE_CHECKING:
    from ..agent.run_manager import RunManager
    from ..store import SessionStore

logger = logging.getLogger(__name__)

SendFrame = Callable[[dict[str, Any]], Awaitable[None]]


def _now_ms() -> int:
    return int(time.time() * 1000)


class CompanionCoordinator:
    """每个 WebSocket 连接一个；engine 也每连接一个（M0 单客户端）。"""

    def __init__(
        self,
        engine: AttentionEngine,
        manager: RunManager,
        send_frame: SendFrame,
        *,
        store: SessionStore | None = None,
        session_id: str = "default",
        run_id_gen: Callable[[], str] | None = None,
        ask_expiry_checker: bool = True,
    ) -> None:
        self._engine = engine
        self._manager = manager
        self._send = send_frame
        self._store = store
        self._session_id = session_id
        self._run_id_gen = run_id_gen or (lambda: f"r-{uuid.uuid4().hex[:12]}")
        # ask 过期巡检：expiry_checker=False 关闭（测试用），生产由 ready 巡检驱动
        self._ask_expiry_checker = ask_expiry_checker
        # 已下发 companion.intent 的 intentId → 到期时刻（无声过期巡检）
        self._asks: dict[str, tuple[str | None, int]] = {}

    # ------------------------------------------------------------------
    # 信号入口（ws 命令分发调用）
    # ------------------------------------------------------------------
    async def handle_signal(self, data: CompanionSignalData) -> None:
        if data.kind == "intent_response":
            await self._handle_intent_response(data)
            return
        signal = Signal(
            signal_id=data.signal_id,
            kind=data.kind,
            occurred_at=data.occurred_at,
            salience=data.salience,
            dedupe_key=data.dedupe_key,
            not_before=data.not_before,
            expires_at=data.expires_at,
            payload=data.payload,
        )
        for intent in self._engine.submit(signal):
            await self._execute(intent)

    async def pump(self) -> None:
        """周期巡检：挂起到期 + ask 无声过期（上层定时调用）。"""
        for intent in self._engine.ready_intents():
            await self._execute(intent)
        if self._ask_expiry_checker:
            await self._expire_asks()

    # ------------------------------------------------------------------
    # run 生命周期回调（RunManager 钩子）
    # ------------------------------------------------------------------
    def notify_run_active(self, active: bool) -> None:
        self._engine.notify_run_active(active)

    def notify_user_message(self) -> None:
        self._engine.notify_user_message()

    async def on_run_finished(self, reason: str) -> None:
        """proactive run 收口：cancelled/error 视为未回应（ask 衰减记账）。"""
        if reason in ("cancelled", "interrupted"):
            for intent_id, (key, _exp) in list(self._asks.items()):
                self._engine.notify_ask_expired_unanswered(key)
                self._engine.forget_delivered(intent_id)
                self._asks.pop(intent_id, None)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    async def _execute(self, intent: Intent) -> None:
        """执行通过门控的意图：发 companion.intent + trigger 落盘 + proactive run。"""
        if intent.kind not in ("speak_intent", "ask_intent") or not intent.action:
            # action_intent 首批无来源：词表预留（见 engine._classify）
            logger.info("跳过不可执行的意图类型：%s", intent.kind)
            return
        expires = intent.expires_at or (_now_ms() + self._engine.settings.ask_expires_ms)
        with contextlib.suppress(Exception):
            await self._send(
                make_frame(
                    EVENT_TYPES["companion.intent"],
                    CompanionIntentData(
                        intent_id=intent.intent_id,
                        action=intent.action,
                        kind=intent.signal.kind,
                        quick_replies=list(intent.quick_replies),
                        expires_at=intent.expires_at,
                    ),
                    _now_ms(),
                )
            )
        if intent.action == "ask":
            self._asks[intent.intent_id] = (intent.dedupe_key, expires)
        if self._store is not None:
            with contextlib.suppress(Exception):
                await self._store.add_trigger(
                    intent.intent_id,
                    self._session_id,
                    kind=intent.signal.kind,
                    intent_kind=intent.kind,
                    dedupe_key=intent.dedupe_key,
                )
        await self._start_proactive_run(intent)

    async def _start_proactive_run(self, intent: Intent) -> None:
        from ..agent.run_manager import ProactiveStart  # 局部导入防循环

        await self._manager.start_proactive_run(
            ProactiveStart(
                run_id=self._run_id_gen(),
                session_id=self._session_id,
                intent_id=intent.intent_id,
                text=intent.trigger_prompt,
            )
        )

    async def _handle_intent_response(self, data: CompanionSignalData) -> None:
        payload = data.payload or {}
        intent_id = str(payload.get("intentId", ""))
        decision = str(payload.get("decision", ""))
        if decision not in ("later", "dismiss", "now") or not intent_id:
            logger.warning("intent_response 参数非法，忽略：%s", payload)
            return
        got = self._engine.handle_intent_response(intent_id, decision)
        if decision == "now" and got is not None:
            await self._execute(got)  # 用户点了「现在」：立即重触发
        if decision != "now":
            self._asks.pop(intent_id, None)
        if self._store is not None:
            status = {"later": "snoozed", "dismiss": "dismissed", "now": "answered"}[decision]
            with contextlib.suppress(Exception):
                await self._store.update_trigger_status(intent_id, status)

    async def _expire_asks(self) -> None:
        """ask 无声过期：移除 UI 提示（前端按 expiresAt 自行过期，此处只记账）。"""
        now = _now_ms()
        for intent_id, (key, expires) in list(self._asks.items()):
            if now < expires:
                continue
            self._asks.pop(intent_id, None)
            self._engine.notify_ask_expired_unanswered(key)
            self._engine.forget_delivered(intent_id)
            if self._store is not None:
                with contextlib.suppress(Exception):
                    await self._store.update_trigger_status(intent_id, "expired")


async def start_pump_loop(coordinator: CompanionCoordinator, interval_s: float = 30.0) -> None:
    """巡检任务：挂起意图到期重投 + ask 过期记账。"""
    while True:
        await asyncio.sleep(interval_s)
        with contextlib.suppress(Exception):
            await coordinator.pump()
