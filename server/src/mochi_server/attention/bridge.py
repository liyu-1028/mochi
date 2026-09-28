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
    CharacterCueData,
    CompanionIntentData,
    CompanionSignalData,
    CueBodyChannel,
    CueChannels,
    make_frame,
)
from .engine import AttentionEngine
from .intents import Intent, Signal

if TYPE_CHECKING:
    from ..agent.run_manager import RunManager
    from ..store import SessionStore

logger = logging.getLogger(__name__)

SendFrame = Callable[[dict[str, Any]], Awaitable[None]]

#: action_intent 直发的 cue 参数（本地表演：优先级低于反射 80，TTL 短）
_PROACTIVE_ACTION_PRIORITY = 30
_PROACTIVE_ACTION_TTL_MS = 10_000


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
        # 同类工具连续失败计数（D3：服务端 tool_failed 信号源）
        self._tool_failures: dict[str, int] = {}

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
        """run 活跃通知；run 结束＝自然停顿点 → 立即泵送挂起意图。

        返回协程时由 RunManager._notify_attention 调度为后台任务。
        """
        self._engine.notify_run_active(active)
        if not active:
            return self.pump()  # type: ignore[return-value]

    async def handle_tool_end(self, tool_name: str, success: bool, duration_ms: int) -> None:
        """工具调用收口 → 陪伴信号（D3 服务端信号源）。

        - 成功：清零该工具失败计数；长任务（≥ long_tool_ms）→ tool_finished
          （引擎映射 celebrate 动作，同类 30min 冷却防重复庆祝）；
        - 失败：计数 +1 → tool_failed（引擎同类连续 ≥2 合并为一次 ask；
          单次失败由前端 worried 反射兜底，M-B 既有路径）。
        信号在 run 内到达 → 引擎挂起到 run 结束（自然停顿点）再投。
        """
        now = _now_ms()
        if success:
            self._tool_failures.pop(tool_name, None)
            if duration_ms >= self._engine.settings.long_tool_ms:
                await self.handle_signal(
                    CompanionSignalData(
                        signal_id=f"sig-{uuid.uuid4().hex[:12]}",
                        kind="tool_finished",
                        occurred_at=now,
                        salience=2,
                        dedupe_key=f"tool-finished:{tool_name}",
                        payload={"tool": tool_name, "durationMs": duration_ms},
                    )
                )
            return
        count = self._tool_failures.get(tool_name, 0) + 1
        self._tool_failures[tool_name] = count
        await self.handle_signal(
            CompanionSignalData(
                signal_id=f"sig-{uuid.uuid4().hex[:12]}",
                kind="tool_failed",
                occurred_at=now,
                salience=2,
                dedupe_key=f"tool:{tool_name}",
                payload={"tool": tool_name, "consecutiveFailures": count},
            )
        )

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
        """执行通过门控的意图。

        - action_intent：本地表演——character.cue(source=proactive) 直发，
          不进 LLM、不起 run（§8.6「默认行为」列）；
        - speak/ask：发 companion.intent + trigger 落盘 + proactive run。
        """
        if intent.kind == "action_intent":
            await self._emit_action_cue(intent)
            return
        if intent.kind not in ("speak_intent", "ask_intent") or not intent.action:
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

    async def _emit_action_cue(self, intent: Intent) -> None:
        """action_intent 执行：body 通道语义动作经 character.cue 直发前端。"""
        if not intent.action_id:
            return
        with contextlib.suppress(Exception):
            await self._send(
                make_frame(
                    EVENT_TYPES["character.cue"],
                    CharacterCueData(
                        cue_id=f"c-{uuid.uuid4().hex[:12]}",
                        run_id=None,
                        source="proactive",
                        channels=CueChannels(body=CueBodyChannel(action_id=intent.action_id)),
                        sync="immediate",
                        priority=_PROACTIVE_ACTION_PRIORITY,
                        interrupt_policy="replace",
                        ttl_ms=_PROACTIVE_ACTION_TTL_MS,
                    ),
                    _now_ms(),
                )
            )

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
