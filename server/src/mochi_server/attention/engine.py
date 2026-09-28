"""注意力引擎核心（M-D）：信号 → 意图 → 门控。

设计要点（调研报告 §4.1/§8.2/§8.6、计划 M-D）：
- 两阶段决策：``classify`` 只产出结构化意图；``gate`` 按抑制清单全表裁决；
- 信号只描述事实：引擎不知道「该说什么话」，speak/ask 的措辞交给 LangGraph
  （proactive run），action_intent 由上层直接映射 character.cue；
- 时间经注入 clock（epoch ms）获取，全部门控/冷却/过期可表格化测试；
- 门控未通过 ≠ 丢弃：低优先级意图挂起 pending，用户发消息时取消（验收项）。

引擎不持久化自身状态（预算/冷却随进程重启重置）——勿扰时段是唯一的
持久化门控项，来自 config（AttentionConfig，重启后仍生效，验收项）。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from .intents import GateDecision, Intent, Signal

logger = logging.getLogger(__name__)

#: 默认门控参数（调研报告 §8.6 建议 + 首批保守值）
DEFAULT_SILENCE_WINDOW_MS = 5 * 60 * 1000  # 用户刚发消息后的静默窗
DEFAULT_TOPIC_COOLDOWN_MS = 30 * 60 * 1000  # 同主题冷却
DEFAULT_DISMISS_COOLDOWN_MS = 24 * 60 * 60 * 1000  # 「不用提醒」后的主题冷却
DEFAULT_SNOOZE_MS = 10 * 60 * 1000  # 「稍后」
DEFAULT_HOURLY_BUDGET = 2
DEFAULT_DAILY_BUDGET = 6
DEFAULT_ASK_EXPIRES_MS = 10 * 60 * 1000  # ask_intent 无声过期
DEFAULT_LONG_TOOL_MS = 30_000  # 工具完成超过该时长才算「长任务」值得庆祝
DEFAULT_FOCUS_ACTIVE_MS = 50 * 60 * 1000  # 连续活跃超过该时长才建议休息

#: 可重试的抑制原因（信号到得太早）：挂起到自然停顿点再投，不丢弃。
#: 不可重试（topic_cooldown/topic_dismissed/budget*/unresponded_decay）
#: 语义上短期不会变化 → 直接丢弃（无声）。
_RETRYABLE_REASONS = frozenset({"quiet_hours", "run_active", "user_typing", "user_silence_window"})
#: 挂起重试间隔与最长挂起时长（防止勿扰时段把意图挂到天荒地老）
_PARK_RETRY_MS = 30_000
_PARK_MAX_MS = 30 * 60_000

#: 未回应衰减阈值（验收「连续未回应衰减」）：连续 N 次 ask 未回应 →
#: N≥2 同主题后续 ask 抑制；N≥3 视同 dismiss（24h 冷却）
UNRESPONDED_SUPPRESS_AT = 2
UNRESPONDED_DISMISS_AT = 3


@dataclass(slots=True)
class AttentionSettings:
    """门控参数（config 注入；引擎内不可变）。"""

    quiet_hours: tuple[str, str] | None = None  # ("22:00", "08:00")，跨午夜支持
    silence_window_ms: int = DEFAULT_SILENCE_WINDOW_MS
    topic_cooldown_ms: int = DEFAULT_TOPIC_COOLDOWN_MS
    dismiss_cooldown_ms: int = DEFAULT_DISMISS_COOLDOWN_MS
    snooze_ms: int = DEFAULT_SNOOZE_MS
    hourly_budget: int = DEFAULT_HOURLY_BUDGET
    daily_budget: int = DEFAULT_DAILY_BUDGET
    ask_expires_ms: int = DEFAULT_ASK_EXPIRES_MS
    long_tool_ms: int = DEFAULT_LONG_TOOL_MS
    focus_active_ms: int = DEFAULT_FOCUS_ACTIVE_MS


@dataclass(slots=True)
class PendingIntent:
    """已通过门控但未到 notBefore 的意图（等待自然停顿点）。"""

    intent: Intent
    not_before: int
    #: 「稍后」snooze 的重挂：到期豁免主题冷却——用户显式要求 N 分钟后再问，
    #: 优先于防骚扰冷却（否则 snooze 必被 30min 冷却吞掉，功能形同虚设）
    exempt_topic_cooldown: bool = False
    #: 挂起期限（epoch ms）：超过即无声丢弃（防勿扰把意图挂成陈年旧账）
    expires_at: int | None = None


@dataclass(slots=True)
class AttentionState:
    """引擎运行时状态（进程内，不持久化）。"""

    last_user_message_ms: int | None = None
    run_active: bool = False
    user_typing: bool = False
    topic_last_fired: dict[str, int] = field(default_factory=dict)
    topic_dismissed_at: dict[str, int] = field(default_factory=dict)
    topic_unresponded: dict[str, int] = field(default_factory=dict)
    fired_hourly: list[int] = field(default_factory=list)  # speak/ask 放行时刻
    fired_daily: list[int] = field(default_factory=list)
    consecutive_failures: dict[str, int] = field(default_factory=dict)  # 工具失败合并


def _quiet_hours_match(now_ms: int, window: tuple[str, str]) -> bool:
    """勿扰时段判断（本地时区；支持跨午夜，如 22:00–08:00）。

    边界约定：start 含、end 不含（22:00:00 起拦，08:00:00 放行）。
    """
    import datetime as _dt

    local = _dt.datetime.fromtimestamp(now_ms / 1000)
    minutes = local.hour * 60 + local.minute
    start_h, start_m = window[0].split(":")
    end_h, end_m = window[1].split(":")
    start = int(start_h) * 60 + int(start_m)
    end = int(end_h) * 60 + int(end_m)
    if start == end:
        return False  # 空窗口
    if start < end:
        return start <= minutes < end
    return minutes >= start or minutes < end  # 跨午夜


class AttentionEngine:
    """陪伴注意力引擎：每连接一个实例（与 RunManager 同生命周期，M0 单客户端）。"""

    def __init__(
        self,
        settings: AttentionSettings | None = None,
        *,
        clock: Callable[[], int] | None = None,
        intent_id_gen: Callable[[], str] | None = None,
    ) -> None:
        self._settings = settings or AttentionSettings()
        self._clock = clock or (lambda: _fallback_now())
        self._intent_id_gen = intent_id_gen or (lambda: f"intent-{uuid.uuid4().hex[:12]}")
        self._state = AttentionState()
        self._pending: list[PendingIntent] = []
        # 已交付（门控放行、展示中）的意图：快速操作回传按 intentId 解析，
        # 不只查挂起队列——放行即展示的 ask 不经过 pending
        self._delivered: dict[str, Intent] = {}

    # ------------------------------------------------------------------
    # 外部状态喂入（引擎不主动探测：由管线在事件点调用）
    # ------------------------------------------------------------------
    def notify_user_message(self) -> None:
        """用户发来消息：刷新静默窗 + 取消未展示的低优先级意图（验收项）。"""
        self._state.last_user_message_ms = self._clock()
        self.cancel_pending("user_message")

    def notify_user_typing(self, typing: bool) -> None:
        self._state.user_typing = typing

    def notify_run_active(self, active: bool) -> None:
        self._state.run_active = active

    def notify_intent_answered(self, dedupe_key: str | None) -> None:
        """用户回应了 ask（快速操作或直接回复）：清零未回应衰减计数。"""
        if dedupe_key:
            self._state.topic_unresponded.pop(dedupe_key, None)

    # ------------------------------------------------------------------
    # 信号入口
    # ------------------------------------------------------------------
    def submit(self, signal: Signal) -> list[Intent]:
        """信号入口：返回本信号直接产出的可执行意图（可能为空）。

        - 过期信号无声丢弃（不计数为抑制——那是正常生命周期）；
        - silent 意图不返回（仅内部状态更新）；action/speak/ask 经门控后返回。
        """
        now = self._clock()
        if signal.expires_at is not None and signal.expires_at <= now:
            logger.info("信号已过期，丢弃：%s kind=%s", signal.signal_id, signal.kind)
            return []
        intent = self._classify(signal)
        if intent.kind == "silent":
            return []
        if intent.kind == "action_intent":
            # 动作意图＝本地表演（等价反射），只受勿扰约束，不走开口门控
            if self._settings.quiet_hours is not None and _quiet_hours_match(
                now, self._settings.quiet_hours
            ):
                return []  # 勿扰时段动作也停（验收：勿扰重启仍生效）
            return self._deliver(intent)
        decision = self.gate(intent, exempt_silence_window=self._is_run_scoped(intent))
        if not decision.allowed:
            if decision.reason in _RETRYABLE_REASONS:
                # 到得太早（run 进行中/静默窗/勿扰/输入中）：挂起等自然停顿点
                self._park(intent, now, retry=True)
                return []
            logger.info(
                "意图被抑制：%s kind=%s 原因=%s", intent.intent_id, intent.kind, decision.reason
            )
            return []
        # notBefore 未到：先挂起（到点经 ready_intents 重新门控再交付）
        not_before = signal.not_before
        if not_before is not None and not_before > now:
            self._pending.append(PendingIntent(intent, not_before))
            return []
        return self._deliver(intent)

    def _park(self, intent: Intent, now: int, *, retry: bool) -> None:
        """挂起意图到自然停顿点（可重试抑制）；带上挂起期限防陈旧。"""
        deadline = now + _PARK_MAX_MS
        if intent.expires_at is not None:
            deadline = min(deadline, intent.expires_at)
        self._pending.append(
            PendingIntent(
                intent,
                not_before=now + _PARK_RETRY_MS if retry else now,
                expires_at=deadline,
            )
        )

    def ready_intents(self) -> list[Intent]:
        """巡检挂起队列：notBefore 已到的意图重新门控，通过则交付。"""
        now = self._clock()
        ready: list[Intent] = []
        keep: list[PendingIntent] = []
        for pending in self._pending:
            if pending.expires_at is not None and now >= pending.expires_at:
                continue  # 挂起过期：无声丢弃（勿扰没结束/一直没等到停顿）
            if pending.not_before > now:
                keep.append(pending)
                continue
            decision = self.gate(
                pending.intent,
                exempt_topic_cooldown=pending.exempt_topic_cooldown,
                exempt_silence_window=self._is_run_scoped(pending.intent),
            )
            if decision.allowed:
                ready.extend(self._deliver(pending.intent))
            else:
                # 到期但门控不再通过（如勿扰开始）：视情况回挂或放弃
                if decision.reason in ("topic_cooldown", "topic_dismissed", "budget"):
                    continue  # 放弃（无声过期）
                keep.append(pending)  # 勿扰/静默窗/忙碌：继续等
        self._pending = keep
        return ready

    def _deliver(self, intent: Intent) -> list[Intent]:
        """登记已交付意图（供快速操作回传解析）并交付上层。"""
        self._record_fired(intent)
        self._delivered[intent.intent_id] = intent
        if len(self._delivered) > 50:  # 容量兜底：只保留最近 50 个
            for old_id in list(self._delivered)[:-50]:
                self._delivered.pop(old_id, None)
        return [intent]

    def forget_delivered(self, intent_id: str) -> None:
        """意图生命周期终结（无声过期/已执行）后由上层调用，清理登记。"""
        self._delivered.pop(intent_id, None)

    def cancel_pending(self, reason: str) -> int:
        """取消全部挂起意图（用户发消息/开始输入）；返回取消数。"""
        n = len(self._pending)
        if n:
            logger.info("取消挂起意图 %d 个：%s", n, reason)
        self._pending.clear()
        return n

    def handle_intent_response(self, intent_id: str, decision: str) -> Intent | None:
        """ask 快速操作回传：later → snooze 重挂；dismiss → 主题冷却；now → 交给上层立即执行。

        intentId 先查挂起队列再查已交付登记（放行即展示的 ask 不经过 pending）。
        """
        now = self._clock()
        target: PendingIntent | None = None
        for pending in self._pending:
            if pending.intent.intent_id == intent_id:
                target = pending
                break
        intent = target.intent if target is not None else self._delivered.get(intent_id)
        key = intent.dedupe_key if intent else None
        if decision == "later":
            if key:
                self._state.topic_last_fired[key] = now
            if target is not None:
                self._pending.remove(target)
                self._pending.append(
                    PendingIntent(
                        intent,
                        now + self._settings.snooze_ms,
                        exempt_topic_cooldown=True,
                    )
                )
            else:
                # 已交付意图的「稍后」：登记为 snooze 重挂（豁免主题冷却）
                self._delivered.pop(intent_id, None)
                self._pending.append(
                    PendingIntent(
                        intent,
                        now + self._settings.snooze_ms,
                        exempt_topic_cooldown=True,
                    )
                )
            return None
        if decision == "dismiss":
            if target is not None:
                self._pending.remove(target)
            self._delivered.pop(intent_id, None)
            if key:
                self._state.topic_dismissed_at[key] = now
                self._state.topic_unresponded.pop(key, None)
            return None
        # now：移除登记（上层立即触发 proactive run）；回应清零衰减
        if target is not None:
            self._pending.remove(target)
        self._delivered.pop(intent_id, None)
        self.notify_intent_answered(key)
        return intent

    # ------------------------------------------------------------------
    # 第一阶段：信号 → 意图（D3 首批映射表）
    # ------------------------------------------------------------------
    def _classify(self, signal: Signal) -> Intent:
        """信号 → 意图（D3 首批映射，调研报告 §8.6 表）。

        映射规则：tool_finished 长任务 → speak（庆祝）；tool_failed 同主题
        连续 ≥2 → ask（像是卡住了）；focus 连续活跃超阈 → 低优先级 ask
        （休息提醒）；commitment_due → ask；其余一律 silent（克制默认）。
        """
        intent_id = self._intent_id_gen()
        kind = signal.kind
        payload = signal.payload
        key = signal.dedupe_key
        if kind == "tool_finished":
            duration = _as_int(payload.get("durationMs"))
            if duration >= self._settings.long_tool_ms:
                # §8.6 表「默认行为」列：立即短庆祝＝本地动作（非 LLM 说话）
                return Intent(
                    intent_id=intent_id,
                    kind="action_intent",
                    action_id="celebrate",
                    signal=signal,
                    dedupe_key=key or f"tool-finished:{payload.get('tool', 'unknown')}",
                )
            return Intent(intent_id=intent_id, kind="silent", signal=signal)
        if kind == "tool_failed":
            key = key or f"tool:{payload.get('tool', 'unknown')}"
            count = _as_int(payload.get("consecutiveFailures"), 1)
            self._state.consecutive_failures[key] = count
            if count < 2:
                return Intent(intent_id=intent_id, kind="silent", signal=signal, dedupe_key=key)
            return Intent(
                intent_id=intent_id,
                kind="ask_intent",
                action="ask",
                signal=signal,
                dedupe_key=key,
                quick_replies=("later", "dismiss"),
                expires_at=self._clock() + self._settings.ask_expires_ms,
                trigger_prompt=(
                    f"（系统提示：工具 {payload.get('tool', '任务')} 已连续失败 "
                    f"{count} 次。请用一句话表示关心，并询问是否需要换个方向。"
                    f"不要使用任何工具。）"
                ),
            )
        if kind == "focus_session":
            active_ms = _as_int(payload.get("activeMs"))
            if active_ms < self._settings.focus_active_ms:
                return Intent(intent_id=intent_id, kind="silent", signal=signal)
            return Intent(
                intent_id=intent_id,
                kind="ask_intent",
                action="ask",
                signal=signal,
                dedupe_key=key,
                quick_replies=("later", "dismiss"),
                expires_at=self._clock() + self._settings.ask_expires_ms,
                priority=0,  # 低优先级：用户发消息即取消
                trigger_prompt=(
                    f"（系统提示：用户已连续工作约 {active_ms // 60000} 分钟。"
                    f"请用一句话建议休息一下。不要使用任何工具。）"
                ),
            )
        if kind == "commitment_due":
            return Intent(
                intent_id=intent_id,
                kind="ask_intent",
                action="ask",
                signal=signal,
                dedupe_key=key,
                quick_replies=("later", "dismiss"),
                expires_at=self._clock() + self._settings.ask_expires_ms,
                trigger_prompt=(
                    "（系统提示：到了之前约定的时间。请用一句话提醒用户。不要使用任何工具。）"
                ),
            )
        # idle / touch / drag / message / tool_started / tool_needs_user /
        # context_summary / intent_response（经 handle_intent_response 处理）
        return Intent(intent_id=intent_id, kind="silent", signal=signal)

    # ------------------------------------------------------------------
    # 第二阶段：门控规则表（调研报告 §8.6 抑制清单全表，按序短路）
    # ------------------------------------------------------------------
    #: run 内来源的信号（工具生命周期）：run 结束即自然停顿点，
    #: 豁免用户静默窗——否则启动 run 的那条用户消息会把「卡住了」提问
    #: 拖到 5 分钟后（§8.6 合并提问的时机语义被静默窗吞掉）。
    #: 环境信号（focus_session 等）仍受静默窗约束。
    _RUN_SCOPED_KINDS = frozenset({"tool_finished", "tool_failed"})

    def gate(
        self,
        intent: Intent,
        *,
        exempt_topic_cooldown: bool = False,
        exempt_silence_window: bool = False,
    ) -> GateDecision:
        now = self._clock()
        s = self._settings
        # 1. 勿扰/安静时段（持久化 config；speak/ask/action 全部抑制）
        if s.quiet_hours is not None and _quiet_hours_match(now, s.quiet_hours):
            return GateDecision.suppress("quiet_hours")
        # 2. 回合进行中（角色正在说话或 run 仍在进行）
        if self._state.run_active:
            return GateDecision.suppress("run_active")
        # 3. 用户正在输入（低优先级意图取消，普通意图抑制）
        if self._state.user_typing and intent.priority == 0:
            return GateDecision.suppress("user_typing")
        # 4. 用户刚发消息的静默窗（run 内来源信号豁免：见 _RUN_SCOPED_KINDS）
        last = self._state.last_user_message_ms
        if not exempt_silence_window and last is not None and now - last < s.silence_window_ms:
            return GateDecision.suppress("user_silence_window")
        # 5. 同主题冷却（snooze 重挂豁免——用户显式要求优先）
        key = intent.dedupe_key
        if key and not exempt_topic_cooldown:
            fired = self._state.topic_last_fired.get(key)
            if fired is not None and now - fired < s.topic_cooldown_ms:
                return GateDecision.suppress("topic_cooldown")
            dismissed = self._state.topic_dismissed_at.get(key)
            if dismissed is not None and now - dismissed < s.dismiss_cooldown_ms:
                return GateDecision.suppress("topic_dismissed")
            # 6. 连续未回应衰减（仅 ask）
            if intent.kind == "ask_intent":
                unresponded = self._state.topic_unresponded.get(key, 0)
                if unresponded >= UNRESPONDED_SUPPRESS_AT:
                    return GateDecision.suppress("unresponded_decay")
        # 7. 小时/每日预算（仅真正开口的 speak/ask 计入）
        if intent.kind in ("speak_intent", "ask_intent"):
            window_start = now - 3_600_000
            if sum(t > window_start for t in self._state.fired_hourly) >= s.hourly_budget:
                return GateDecision.suppress("budget_hourly")
            day_start = now - 86_400_000
            if sum(t > day_start for t in self._state.fired_daily) >= s.daily_budget:
                return GateDecision.suppress("budget_daily")
        return GateDecision.allow()

    def _is_run_scoped(self, intent: Intent) -> bool:
        return intent.signal.kind in self._RUN_SCOPED_KINDS

    def _record_fired(self, intent: Intent) -> None:
        now = self._clock()
        if intent.dedupe_key:
            self._state.topic_last_fired[intent.dedupe_key] = now
        if intent.kind in ("speak_intent", "ask_intent"):
            self._state.fired_hourly.append(now)
            self._state.fired_daily.append(now)

    # ------------------------------------------------------------------
    # 未回应衰减记账（上层在 ask 展示后调用；用户回应走 notify_intent_answered）
    # ------------------------------------------------------------------
    def notify_ask_expired_unanswered(self, dedupe_key: str | None) -> None:
        """ask 无声过期未被回应：计数 +1；达 UNRESPONDED_DISMISS_AT 视同 dismiss。

        上层同时调用 forget_delivered(intent_id) 清理登记。
        """
        if not dedupe_key:
            return
        count = self._state.topic_unresponded.get(dedupe_key, 0) + 1
        self._state.topic_unresponded[dedupe_key] = count
        if count >= UNRESPONDED_DISMISS_AT:
            self._state.topic_dismissed_at[dedupe_key] = self._clock()
            self._state.topic_unresponded.pop(dedupe_key, None)
            logger.info("连续未回应 %d 次，主题 %s 进入 24h 冷却", count, dedupe_key)

    @property
    def settings(self) -> AttentionSettings:
        return self._settings


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _fallback_now() -> int:
    import time

    return int(time.time() * 1000)


def settings_from_config(config: object) -> AttentionSettings:
    """AttentionConfig（config.py，持久化）→ 引擎 AttentionSettings。

    放此处而非 config.py：避免 config 模块依赖引擎（保持 config 纯数据）。
    """
    from ..config import AttentionConfig  # 局部导入防循环

    assert isinstance(config, AttentionConfig)
    return AttentionSettings(
        quiet_hours=tuple(config.quiet_hours) if config.quiet_hours else None,
        silence_window_ms=config.silence_window_ms,
        topic_cooldown_ms=config.topic_cooldown_ms,
        snooze_ms=config.snooze_ms,
        hourly_budget=config.hourly_budget,
        daily_budget=config.daily_budget,
        ask_expires_ms=config.ask_expires_ms,
        long_tool_ms=config.long_tool_ms,
        focus_active_ms=config.focus_active_ms,
    )
