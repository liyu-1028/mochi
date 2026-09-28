"""注意力引擎门控规则表测试（M-D）。

验收要求：门控规则一条规则一条自动化测试（覆盖调研报告 §8.6 抑制清单全项），
同主题冷却、每小时/每日上限、连续未回应衰减均有边界值测试。
时间全部经注入 clock——无 sleep、无真实等待。
"""

from __future__ import annotations

from mochi_server.attention.engine import (
    UNRESPONDED_DISMISS_AT,
    UNRESPONDED_SUPPRESS_AT,
    AttentionEngine,
    AttentionSettings,
    _quiet_hours_match,
)
from mochi_server.attention.intents import Signal

HOUR = 3_600_000
DAY = 86_400_000


class FakeClock:
    def __init__(self, start: int = 1_758_900_000_000) -> None:
        self.now = start

    def __call__(self) -> int:
        return self.now

    def advance(self, ms: int) -> None:
        self.now += ms


def make_engine(**settings: object) -> tuple[AttentionEngine, FakeClock]:
    clock = FakeClock()
    engine = AttentionEngine(AttentionSettings(**settings), clock=clock)  # type: ignore[arg-type]
    return engine, clock


def sig(kind: str, **kw: object) -> Signal:
    return Signal(
        signal_id=kw.pop("signal_id", f"s-{kind}-{kw.get('dedupe_key', '')}"),
        kind=kind,
        occurred_at=0,
        salience=kw.pop("salience", 2),
        payload=kw.pop("payload", {}),
        **kw,
    )


# ---------------------------------------------------------------------------
# 第一阶段：信号 → 意图映射（D3 首批）
# ---------------------------------------------------------------------------
class TestClassify:
    def test_short_tool_finished_is_silent(self) -> None:
        engine, _ = make_engine()
        out = engine.submit(sig("tool_finished", payload={"tool": "bash", "durationMs": 100}))
        assert out == []

    def test_long_tool_finished_becomes_celebrate_action(self) -> None:
        """§8.6 表「默认行为」列：立即短庆祝＝本地动作（action_intent）。

        D3 决策：speak 类「要不要我帮你检查结果」属可选话语，v1 不做——
        庆祝经 character.cue(source=proactive) 直发，不进 LLM。
        """
        engine, _ = make_engine()
        out = engine.submit(sig("tool_finished", payload={"tool": "bash", "durationMs": 40_000}))
        assert len(out) == 1
        assert out[0].kind == "action_intent"
        assert out[0].action_id == "celebrate"
        assert out[0].dedupe_key == "tool-finished:bash"

    def test_single_tool_failure_is_silent(self) -> None:
        engine, _ = make_engine()
        out = engine.submit(
            sig(
                "tool_failed",
                dedupe_key="tool:bash",
                payload={"tool": "bash", "consecutiveFailures": 1},
            )
        )
        assert out == []

    def test_consecutive_failures_merge_into_one_ask(self) -> None:
        """同类错误连续发生：合并后只问一次（§8.6）。"""
        engine, _ = make_engine()
        out = engine.submit(
            sig(
                "tool_failed",
                dedupe_key="tool:bash",
                payload={"tool": "bash", "consecutiveFailures": 3},
            )
        )
        assert len(out) == 1
        assert out[0].kind == "ask_intent"
        assert "3 次" in out[0].trigger_prompt

    def test_focus_session_below_threshold_is_silent(self) -> None:
        engine, _ = make_engine()
        out = engine.submit(sig("focus_session", payload={"activeMs": 10 * 60_000}))
        assert out == []

    def test_focus_session_above_threshold_is_low_priority_ask(self) -> None:
        engine, _ = make_engine()
        out = engine.submit(sig("focus_session", payload={"activeMs": 60 * 60_000}))
        assert len(out) == 1
        assert out[0].kind == "ask_intent"
        assert out[0].priority == 0  # 低优先级：用户发消息即取消
        assert out[0].quick_replies == ("later", "dismiss")
        assert out[0].expires_at is not None

    def test_idle_signal_is_silent(self) -> None:
        """idle 只记录不主动说话（克制默认）。"""
        engine, _ = make_engine()
        assert engine.submit(sig("idle", payload={"idleMs": HOUR})) == []

    def test_expired_signal_dropped_silently(self) -> None:
        """expiresAt 已过的信号无声丢弃（正常生命周期，非抑制）。"""
        engine, clock = make_engine()
        clock.advance(11 * 60_000)
        assert (
            engine.submit(
                sig("focus_session", payload={"activeMs": HOUR}, expires_at=clock.now - 1)
            )
            == []
        )


# ---------------------------------------------------------------------------
# 第二阶段：门控规则表（§8.6 抑制清单全项，一条规则一条测试）
# ---------------------------------------------------------------------------
class TestGateRules:
    def _ask(self, engine: AttentionEngine, key: str = "k1") -> list:
        return engine.submit(sig("commitment_due", dedupe_key=key, payload={}))

    def test_quiet_hours_suppresses(self) -> None:
        """勿扰/安静时段（持久化 config）：speak/ask 全部抑制。"""
        engine, clock = make_engine(quiet_hours=("22:00", "08:00"))
        clock.now = int(__import__("datetime").datetime(2026, 9, 28, 23, 0).timestamp() * 1000)
        assert self._ask(engine) == []

    def test_quiet_hours_crosses_midnight(self) -> None:
        assert _quiet_hours_match(
            int(__import__("datetime").datetime(2026, 9, 28, 23, 30).timestamp() * 1000),
            ("22:00", "08:00"),
        )
        assert _quiet_hours_match(
            int(__import__("datetime").datetime(2026, 9, 28, 3, 30).timestamp() * 1000),
            ("22:00", "08:00"),
        )
        assert not _quiet_hours_match(
            int(__import__("datetime").datetime(2026, 9, 28, 12, 0).timestamp() * 1000),
            ("22:00", "08:00"),
        )

    def test_quiet_hours_boundary_end_releases(self) -> None:
        """边界：start 含（22:00 起拦）、end 不含（08:00 放行）。"""
        assert _quiet_hours_match(
            int(__import__("datetime").datetime(2026, 9, 28, 22, 0).timestamp() * 1000),
            ("22:00", "08:00"),
        )
        assert not _quiet_hours_match(
            int(__import__("datetime").datetime(2026, 9, 28, 8, 0).timestamp() * 1000),
            ("22:00", "08:00"),
        )

    def test_run_active_suppresses(self) -> None:
        """角色正在说话或 run 仍在进行 → 抑制。"""
        engine, _ = make_engine()
        engine.notify_run_active(True)
        assert self._ask(engine) == []

    def test_user_typing_cancels_low_priority_only(self) -> None:
        """用户正在输入：低优先级意图抑制；普通意图不受影响。"""
        engine, _ = make_engine()
        engine.notify_user_typing(True)
        assert len(self._ask(engine, "low")) == 1  # commitment_due pri=1 不受 typing 影响
        focus = engine.submit(sig("focus_session", payload={"activeMs": HOUR}))
        assert focus == []  # 低优先级被抑制

    def test_user_silence_window_boundary(self) -> None:
        """用户刚发消息 → 静默窗内抑制；窗口外放行（边界 5min）。"""
        engine, clock = make_engine()
        engine.notify_user_message()
        clock.advance(5 * 60_000 - 1)
        assert self._ask(engine) == []  # 差 1ms 到窗
        clock.advance(1)
        assert len(self._ask(engine)) == 1  # 恰好到窗

    def test_topic_cooldown_boundary(self) -> None:
        """同主题 30min 冷却：窗口内抑制、窗口外放行。"""
        engine, clock = make_engine()
        assert len(self._ask(engine, "t")) == 1
        clock.advance(30 * 60_000 - 1)
        assert self._ask(engine, "t") == []
        clock.advance(1)
        assert len(self._ask(engine, "t")) == 1

    def test_other_topic_not_affected_by_cooldown(self) -> None:
        """不同主题互不影响冷却。"""
        engine, _ = make_engine()
        assert len(self._ask(engine, "a")) == 1
        assert len(self._ask(engine, "b")) == 1

    def test_dismiss_cooldown_24h(self) -> None:
        """「不用提醒」→ 该主题 24h 冷却（边界）。"""
        engine, clock = make_engine()
        first = self._ask(engine, "t")
        assert len(first) == 1
        engine.handle_intent_response(first[0].intent_id, "dismiss")
        clock.advance(DAY - 1)
        assert self._ask(engine, "t") == []
        clock.advance(1)
        assert len(self._ask(engine, "t")) == 1

    def test_unresponded_decay_boundaries(self) -> None:
        """连续未回应衰减：1 次放行、≥2 抑制、≥3 视同 dismiss（24h）。"""
        engine, clock = make_engine()
        for i in range(1, UNRESPONDED_DISMISS_AT + 1):
            out = self._ask(engine, "t")
            if i <= UNRESPONDED_SUPPRESS_AT:
                assert len(out) == 1  # 前两次放行
                engine.notify_ask_expired_unanswered("t")
            clock.advance(HOUR)
        # 第 3 次未回应已视同 dismiss → 后续 24h 内抑制
        assert self._ask(engine, "t") == []

    def test_answered_resets_decay(self) -> None:
        """用户回应（notify_intent_answered）清零衰减计数。"""
        engine, clock = make_engine()
        self._ask(engine, "t")
        engine.notify_ask_expired_unanswered("t")
        engine.notify_intent_answered("t")
        clock.advance(HOUR)
        assert len(self._ask(engine, "t")) == 1

    def test_hourly_budget_boundary(self) -> None:
        """每小时预算 2：第 2 条放行、第 3 条抑制；滑窗过期后恢复。"""
        engine, clock = make_engine()
        for i in range(2):
            assert len(self._ask(engine, f"h{i}")) == 1
        assert self._ask(engine, "h2") == []  # 第 3 条超预算
        clock.advance(HOUR + 1)
        assert len(self._ask(engine, "h3")) == 1  # 滑窗过期恢复

    def test_daily_budget_boundary(self) -> None:
        """每日预算 6：第 6 条放行、第 7 条抑制（每小时拉开，绕过小时预算）。"""
        engine, clock = make_engine()
        for i in range(6):
            clock.advance(HOUR + 1)  # 拉开小时窗
            assert len(engine.submit(sig("commitment_due", dedupe_key=f"d{i}", payload={}))) == 1, i
        clock.advance(HOUR + 1)
        assert engine.submit(sig("commitment_due", dedupe_key="d6", payload={})) == []


# ---------------------------------------------------------------------------
# 挂起队列（pending）：notBefore、取消、snooze/dismiss/now
# ---------------------------------------------------------------------------
class TestPending:
    def test_not_before_parks_until_due(self) -> None:
        """notBefore 未到 → 挂起；到点 ready。"""
        engine, clock = make_engine()
        engine.submit(sig("commitment_due", dedupe_key="k", not_before=clock.now + HOUR))
        assert engine.ready_intents() == []
        clock.advance(HOUR)
        ready = engine.ready_intents()
        assert len(ready) == 1 and ready[0].kind == "ask_intent"

    def test_user_message_cancels_pending(self) -> None:
        """验收：用户发新消息 → 未展示的低优先级 proactive intent 被取消。"""
        engine, clock = make_engine()
        engine.submit(sig("commitment_due", dedupe_key="k", not_before=clock.now + HOUR))
        assert engine.cancel_pending("user_message") == 1
        clock.advance(2 * HOUR)
        assert engine.ready_intents() == []

    def test_later_snoozes_topic(self) -> None:
        """「稍后」→ snooze 重挂（豁免主题冷却）+ 等待期新信号仍被冷却。"""
        engine, clock = make_engine()
        out = self._fire(engine)
        assert out is not None
        engine.handle_intent_response(out.intent_id, "later")
        clock.advance(5 * 60_000)
        # snooze 等待期间：同主题新信号被主题冷却拦住（不叠加第二个意图）
        assert engine.submit(sig("commitment_due", dedupe_key="k", payload={})) == []
        clock.advance(5 * 60_000 + 1)  # 距「稍后」10min+1ms
        ready = engine.ready_intents()
        assert len(ready) == 1 and ready[0].intent_id == out.intent_id

    def test_dismiss_removes_pending_and_cools_topic(self) -> None:
        engine, clock = make_engine()
        out = self._fire(engine)
        engine.handle_intent_response(out.intent_id, "dismiss")
        clock.advance(2 * HOUR)
        assert engine.ready_intents() == []
        assert engine.submit(sig("commitment_due", dedupe_key="k", payload={})) == []

    def test_now_returns_intent_for_execution(self) -> None:
        engine, _ = make_engine()
        out = self._fire(engine)
        got = engine.handle_intent_response(out.intent_id, "now")
        assert got is not None and got.intent_id == out.intent_id

    def _fire(self, engine: AttentionEngine):
        out = engine.submit(sig("commitment_due", dedupe_key="k", payload={}))
        assert len(out) == 1
        return out[0]


# ---------------------------------------------------------------------------
# 预算记账边界：silent 不计入 speak/ask 预算
# ---------------------------------------------------------------------------
class TestBudgetAccounting:
    def test_silent_does_not_consume_budget(self) -> None:
        engine, _ = make_engine()
        for _ in range(10):
            engine.submit(sig("idle"))
        out = engine.submit(sig("commitment_due", dedupe_key="k", payload={}))
        assert len(out) == 1


# ---------------------------------------------------------------------------
# 验收：勿扰设置重启后仍生效（持久化测试）
# ---------------------------------------------------------------------------
class TestQuietHoursPersistence:
    def test_quiet_hours_survives_config_reload(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """写入 config.toml 的 [attention] 勿扰时段，重新加载后引擎仍抑制。"""
        import datetime as dt

        from mochi_server.attention.engine import settings_from_config
        from mochi_server.config import load_config, save_config

        cfg_path = tmp_path / "config.toml"
        cfg = load_config(cfg_path)  # 首启生成默认
        cfg.attention.quiet_hours = ("22:00", "08:00")
        save_config(cfg_path, cfg)

        reloaded = load_config(cfg_path)  # 「重启」：重新加载
        assert reloaded.attention.quiet_hours == ("22:00", "08:00")

        engine = AttentionEngine(settings_from_config(reloaded.attention))
        # 23:00 仍在勿扰时段（本地时区）
        engine._clock = lambda: int(dt.datetime(2026, 9, 28, 23, 0).timestamp() * 1000)  # type: ignore[method-assign]
        assert engine.submit(sig("commitment_due", dedupe_key="k", payload={})) == []

    def test_default_attention_flag_is_off(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """默认 attention=off：主动陪伴 opt-in（克制默认，零回归锚点）。"""
        from mochi_server.config import load_config

        cfg = load_config(tmp_path / "config.toml")
        assert cfg.agent.attention == "off"

    def test_settings_bridge_maps_all_fields(self) -> None:
        from mochi_server.attention.engine import settings_from_config
        from mochi_server.config import AttentionConfig

        src = AttentionConfig(quiet_hours=("23:00", "07:00"), hourly_budget=1)  # type: ignore[arg-type]
        settings = settings_from_config(src)
        assert settings.quiet_hours == ("23:00", "07:00")
        assert settings.hourly_budget == 1
        assert settings.topic_cooldown_ms == src.topic_cooldown_ms


# ---------------------------------------------------------------------------
# D3：可重试抑制 → 挂起到自然停顿点（不丢信号）
# ---------------------------------------------------------------------------
class TestRetryableParking:
    def test_run_active_parks_until_idle(self) -> None:
        """run 进行中的信号不丢弃：挂起，run 结束后（pump）再门控交付。"""
        engine, clock = make_engine()
        engine.notify_run_active(True)
        assert engine.submit(sig("commitment_due", dedupe_key="k", payload={})) == []
        engine.notify_run_active(False)
        clock.advance(31_000)  # 过挂起重试间隔
        ready = engine.ready_intents()
        # 静默窗（无用户消息）不拦 → 交付
        assert len(ready) == 1 and ready[0].kind == "ask_intent"

    def test_park_respects_user_silence_window(self) -> None:
        """挂起到点时仍在静默窗 → 继续等（不投递也不丢弃）。"""
        engine, clock = make_engine()
        engine.notify_run_active(True)
        engine.notify_user_message()  # 静默窗起点
        assert engine.submit(sig("commitment_due", dedupe_key="k", payload={})) == []
        engine.notify_run_active(False)
        clock.advance(31_000)  # run 空闲但静默窗（5min）未过
        assert engine.ready_intents() == []  # 继续等
        clock.advance(5 * 60_000)
        assert len(engine.ready_intents()) == 1

    def test_park_expires_silently(self) -> None:
        """挂起期限（30min 上限）到期无声丢弃——勿扰整夜不积压旧意图。"""
        engine, clock = make_engine(quiet_hours=("22:00", "08:00"))
        clock.now = int(__import__("datetime").datetime(2026, 9, 28, 23, 0).timestamp() * 1000)
        assert engine.submit(sig("commitment_due", dedupe_key="k", payload={})) == []
        clock.advance(31 * 60_000)  # 过重试间隔 + 挂起上限
        assert engine.ready_intents() == []  # 已过期丢弃
        clock.advance(6 * HOUR)
        assert engine.ready_intents() == []  # 没有陈年旧账

    def test_non_retryable_still_drops(self) -> None:
        """主题冷却/预算类抑制不挂起（语义短期不变，挂起无意义）。"""
        engine, _ = make_engine()
        assert len(engine.submit(sig("commitment_due", dedupe_key="t", payload={}))) == 1
        out = engine.submit(sig("commitment_due", dedupe_key="t", payload={}))
        assert out == []  # 主题冷却：直接丢弃
        assert engine.ready_intents() == []  # 未挂起

    def test_quiet_hours_blocks_action_intent(self) -> None:
        """action_intent 只受勿扰约束（动作＝本地表演，不占预算）。"""
        engine, clock = make_engine(quiet_hours=("22:00", "08:00"))
        clock.now = int(__import__("datetime").datetime(2026, 9, 28, 23, 0).timestamp() * 1000)
        assert (
            engine.submit(sig("tool_finished", payload={"tool": "bash", "durationMs": 40_000}))
            == []
        )
        clock.now = int(__import__("datetime").datetime(2026, 9, 29, 12, 0).timestamp() * 1000)
        out = engine.submit(sig("tool_finished", payload={"tool": "bash", "durationMs": 40_000}))
        assert len(out) == 1 and out[0].action_id == "celebrate"
