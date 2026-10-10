"""注意力管线集成测试（M-D D2b）。

覆盖：
- CompanionCoordinator：信号 → companion.intent 事件 → proactive run 全链路
  （fake agent + fake send）；
- D4 记忆边界（验收）：主动事件后的会话记录中不出现伪造 user message，
  trigger metadata 单独落盘，真正说出后仅记 assistant utterance；
- attention=off（默认）：companion.signal 被忽略，M-C 结束点行为不变；
- RunManager.start_proactive_run：run.started 带 source/intentId、
  text.* 带 source=proactive。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fakes import AIMessageChunk, ScriptedChatModel, make_test_adapter

from mochi_server.agent.llm_agent import LLMAgentService
from mochi_server.agent.run_manager import ProactiveStart, RunManager
from mochi_server.attention.bridge import CompanionCoordinator
from mochi_server.attention.engine import AttentionEngine, AttentionSettings
from mochi_server.events import CompanionSignalData
from mochi_server.store import SessionStore


class FakeSender:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    async def __call__(self, frame: dict[str, Any]) -> None:
        self.frames.append(frame)


def _agent(store: SessionStore | None = None) -> LLMAgentService:
    model = ScriptedChatModel(
        calls=[[AIMessageChunk(content="连续几次都没跑通，要我换个方向试试吗？")]]
    )
    return LLMAgentService(make_test_adapter(model), store=store)


def _signal(kind: str, **payload: Any) -> CompanionSignalData:
    return CompanionSignalData(
        signal_id="s-1",
        kind=kind,
        occurred_at=0,
        salience=2,
        dedupe_key=payload.pop("dedupe_key", None),
        payload=payload,
    )


async def _drain(manager: RunManager) -> None:
    for _ in range(500):
        if not manager.has_active_runs:
            return
        await asyncio.sleep(0)
    raise AssertionError("run 未结束")


# ---------------------------------------------------------------------------
# 信号 → 意图 → proactive run 全链路
# ---------------------------------------------------------------------------
class TestCoordinatorFlow:
    @pytest.mark.asyncio
    async def test_tool_failed_ask_end_to_end(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """同类失败 2 次 → ask → companion.intent + proactive run（source=proactive）。"""
        store = SessionStore(db_path=tmp_path / "s.db")
        sender = FakeSender()
        manager = RunManager(_agent(store), sender)
        engine = AttentionEngine(AttentionSettings(), clock=lambda: 1_000)
        coordinator = CompanionCoordinator(engine, manager, sender, store=store, session_id="sess")
        manager.attach_coordinator(coordinator)

        await coordinator.handle_signal(
            _signal("tool_failed", tool="bash", consecutiveFailures=2, dedupe_key="tool:bash")
        )
        await _drain(manager)

        types = [f["type"] for f in sender.frames]
        assert "companion.intent" in types
        idx = types.index("companion.intent")
        intent = sender.frames[idx]["data"]
        assert intent["action"] == "ask"
        assert intent["quickReplies"] == ["later", "dismiss"]

        run_idx = types.index("run.started")
        run_data = sender.frames[run_idx]["data"]
        assert run_data["source"] == "proactive"
        assert run_data["intentId"] == intent["intentId"]
        # 正文流带 source=proactive（复用 text 事件族，§8 决策点 4）
        text_frames = [f for f in sender.frames if f["type"].startswith("text.")]
        assert text_frames and all(f["data"]["source"] == "proactive" for f in text_frames)
        assert types[-1] == "run.finished"
        await store.close()

    @pytest.mark.asyncio
    async def test_d4_no_forged_user_message(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """验收：主动事件后的会话记录不出现伪造 user message，只有 assistant。"""
        store = SessionStore(db_path=tmp_path / "s.db")
        sender = FakeSender()
        manager = RunManager(_agent(store), sender)
        engine = AttentionEngine(AttentionSettings(), clock=lambda: 1_000)
        coordinator = CompanionCoordinator(engine, manager, sender, store=store, session_id="sess")
        manager.attach_coordinator(coordinator)

        await coordinator.handle_signal(
            _signal("tool_failed", tool="bash", consecutiveFailures=3, dedupe_key="tool:bash")
        )
        await _drain(manager)

        messages = await store.get_messages("sess")
        roles = [m["role"] for m in messages]
        # D4 红线：绝不伪造 user message；真正说出后记 assistant utterance
        assert roles == ["assistant"]
        assert "换个方向" in messages[0]["content"]
        # trigger metadata 单独持久化（与 messages 分离）
        async with store._lock:
            conn = await store._open()
            cursor = await conn.execute("SELECT kind, intent_kind, dedupe_key FROM triggers")
            rows = [tuple(r) for r in await cursor.fetchall()]
        assert rows == [("tool_failed", "ask_intent", "tool:bash")]
        await store.close()

    @pytest.mark.asyncio
    async def test_intent_response_dismiss_stops_topic(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """「不用提醒」：intent 消失 + 主题冷却（后续同类信号不触发）。"""
        store = SessionStore(db_path=tmp_path / "s.db")
        sender = FakeSender()
        manager = RunManager(_agent(store), sender)
        clock = [1_000]
        engine = AttentionEngine(AttentionSettings(), clock=lambda: clock[0])
        coordinator = CompanionCoordinator(engine, manager, sender, store=store, session_id="sess")

        await coordinator.handle_signal(
            _signal("tool_failed", tool="bash", consecutiveFailures=2, dedupe_key="tool:bash")
        )
        intent_id = next(
            f["data"]["intentId"] for f in sender.frames if f["type"] == "companion.intent"
        )
        await coordinator.handle_signal(
            CompanionSignalData(
                signal_id="s-2",
                kind="intent_response",
                occurred_at=0,
                salience=0,
                payload={"intentId": intent_id, "decision": "dismiss"},
            )
        )
        clock[0] += 60_000  # 1 分钟后同类信号再报
        n_before = len(sender.frames)
        await coordinator.handle_signal(
            _signal("tool_failed", tool="bash", consecutiveFailures=4, dedupe_key="tool:bash")
        )
        assert len(sender.frames) == n_before  # 无新 intent / 无新 run
        # trigger 状态落盘为 dismissed
        async with store._lock:
            conn = await store._open()
            cursor = await conn.execute("SELECT status FROM triggers WHERE id = ?", (intent_id,))
            assert (await cursor.fetchone())[0] == "dismissed"
        await store.close()

    @pytest.mark.asyncio
    async def test_user_message_cancels_pending_intent(self) -> None:
        """验收：用户发新消息 → 未展示的低优先级 intent 被取消。"""
        sender = FakeSender()
        manager = RunManager(_agent(), sender)
        clock = [1_000]
        engine = AttentionEngine(AttentionSettings(), clock=lambda: clock[0])
        coordinator = CompanionCoordinator(engine, manager, sender)

        # 挂起中的休息提醒（notBefore=未来，到自然停顿点才展示）
        signal = _signal("focus_session", activeMs=60 * 60_000)
        signal = signal.model_copy(update={"not_before": clock[0] + 10 * 60_000})
        await coordinator.handle_signal(signal)
        clock[0] += 60_000
        coordinator.notify_user_message()  # 用户发消息
        clock[0] += 60_000_000  # 时间流逝（挂起早已到期）
        await coordinator.pump()
        assert not any(f["type"] == "companion.intent" for f in sender.frames)


# ---------------------------------------------------------------------------
# RunManager proactive 生命周期
# ---------------------------------------------------------------------------
class TestProactiveRunLifecycle:
    @pytest.mark.asyncio
    async def test_run_started_carries_source_and_intent(self) -> None:
        sender = FakeSender()
        manager = RunManager(_agent(), sender)
        await manager.start_proactive_run(
            ProactiveStart(
                run_id="r-p1",
                session_id="s",
                intent_id="i-1",
                text="（系统提示：测试）",
            )
        )
        await _drain(manager)
        run_started = next(f for f in sender.frames if f["type"] == "run.started")
        assert run_started["data"]["source"] == "proactive"
        assert run_started["data"]["intentId"] == "i-1"
        assert sender.frames[-1]["data"]["reason"] == "complete"

    @pytest.mark.asyncio
    async def test_proactive_run_silent_when_no_confirmations(self) -> None:
        """proactive 回合完成后无 tool 挂起、无 error（脚本模型直答）。"""
        sender = FakeSender()
        manager = RunManager(_agent(), sender)
        await manager.start_proactive_run(
            ProactiveStart(run_id="r-p2", session_id="s", intent_id="i-2", text="（系统提示）")
        )
        await _drain(manager)
        assert not any(f["type"] == "run.error" for f in sender.frames)


# ---------------------------------------------------------------------------
# attention=off：M-C 结束点行为不变（验收）
# ---------------------------------------------------------------------------
class TestAttentionOff:
    @pytest.mark.asyncio
    async def test_ws_ignores_companion_signal_when_off(self, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """默认 attention=off：ws 收到 companion.signal 不产生任何事件。"""
        from fastapi.testclient import TestClient

        from mochi_server.config import load_config
        from mochi_server.main import create_app

        cfg_path = tmp_path / "config.toml"
        cfg = load_config(cfg_path)
        assert cfg.agent.attention == "off"  # 默认关闭（克制默认）

        app = create_app(config=cfg)
        app.state.store = SessionStore(db_path=tmp_path / "s.db")
        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            ws.send_json(
                {
                    "v": "0.1",
                    "type": "hello",
                    "id": "1",
                    "ts": 0,
                    "data": {"versions": ["0.1"], "client": {"name": "t", "version": "0"}},
                }
            )
            ws.receive_json()  # hello_ack
            ws.send_json(
                {
                    "v": "0.1",
                    "type": "companion.signal",
                    "id": "2",
                    "ts": 0,
                    "data": {
                        "signalId": "s-1",
                        "kind": "tool_failed",
                        "occurredAt": 0,
                        "salience": 2,
                        "dedupeKey": "tool:bash",
                        "payload": {"consecutiveFailures": 3},
                    },
                }
            )
            ws.send_json({"v": "0.1", "type": "ping", "id": "3", "ts": 0, "data": {"token": "x"}})
            pong = ws.receive_json()
            assert pong["type"] == "pong"  # 中间没有插入任何 companion 事件


# ---------------------------------------------------------------------------
# D3：服务端工具信号源（RunManager 嗅探 tool.call.* → coordinator → 信号）
# ---------------------------------------------------------------------------
class TestToolSignalSource:
    async def _run_with_tools(self, manager: RunManager, sender: FakeSender) -> None:  # type: ignore[no-untyped-def]
        """伪 agent：产出 tool.call.start → end(success, 长/短) → 正文。"""
        from mochi_server.events import (
            TextDeltaData,
            TextEndData,
            TextStartData,
            ThinkingEndData,
            ToolCallEndData,
            ToolCallStartData,
        )

        async def fake_run(ctx):  # type: ignore[no-untyped-def]
            yield "thinking.end", ThinkingEndData(run_id=ctx.run_id, message_id="m1")
            yield (
                "tool.call.start",
                ToolCallStartData(
                    run_id=ctx.run_id, tool_call_id="tc1", name="bash", args={"cmd": "ls"}
                ),
            )
            yield (
                "tool.call.end",
                ToolCallEndData(
                    run_id=ctx.run_id, tool_call_id="tc1", status="success", result="ok"
                ),
            )
            yield "text.start", TextStartData(run_id=ctx.run_id, message_id="m1")
            yield "text.delta", TextDeltaData(run_id=ctx.run_id, message_id="m1", delta="完成")
            yield "text.end", TextEndData(run_id=ctx.run_id, message_id="m1", full_text="完成")

        class FakeAgent:
            def run(self, ctx):  # type: ignore[no-untyped-def]
                return fake_run(ctx)

            async def post_run_events(self, ctx):  # type: ignore[no-untyped-def]
                return []

        manager._agent_source = lambda: FakeAgent()  # type: ignore[method-assign]
        from mochi_server.events import ChatSendData

        await manager.start_run(ChatSendData(run_id="r1", session_id="s", text="跑"))
        await _drain(manager)

    @pytest.mark.asyncio
    async def test_short_tool_success_no_signal(self) -> None:
        """短工具成功：无 celebrate（时长 < 阈值），无任何 companion 事件。"""
        sender = FakeSender()
        manager = RunManager(None, sender)  # type: ignore[arg-type]
        engine = AttentionEngine(AttentionSettings(long_tool_ms=10_000), clock=lambda: 1_000)
        coordinator = CompanionCoordinator(engine, manager, sender, ask_expiry_checker=False)
        manager.attach_coordinator(coordinator)
        await self._run_with_tools(manager, sender)
        assert not any(f["type"] == "companion.intent" for f in sender.frames)
        assert not any(f["type"] == "character.cue" for f in sender.frames)

    @pytest.mark.asyncio
    async def test_long_tool_success_emits_celebrate_cue(self) -> None:
        """长任务成功 → action_intent(celebrate) → character.cue(source=proactive)。"""
        sender = FakeSender()
        manager = RunManager(None, sender)  # type: ignore[arg-type]
        # 嗅探时长按真实墙钟差（≈0ms）→ 阈值设 0 使任何工具都算长任务
        engine = AttentionEngine(AttentionSettings(long_tool_ms=0), clock=lambda: 1_000)
        coordinator = CompanionCoordinator(engine, manager, sender, ask_expiry_checker=False)
        manager.attach_coordinator(coordinator)
        await self._run_with_tools(manager, sender)
        for _ in range(50):  # handle_tool_end 是后台任务：让出事件循环
            await asyncio.sleep(0)
        cues = [f for f in sender.frames if f["type"] == "character.cue"]
        assert len(cues) == 1
        data = cues[0]["data"]
        assert data["source"] == "proactive"
        assert data["channels"]["body"]["actionId"] == "celebrate"
        assert data["sync"] == "immediate"
        # 无 run、无 LLM：不产生 proactive 回合
        assert not any(
            f["type"] == "run.started" and f["data"].get("source") == "proactive"
            for f in sender.frames
        )

    @pytest.mark.asyncio
    async def test_tool_failures_merge_to_ask_after_run(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """连续失败 ×2（两个回合）→ run 结束（自然停顿）后 ask 交付。

        豁免静默窗（run 内来源）+ 挂起重试间隔归零（测试时钟冻结）。
        """
        import mochi_server.attention.engine as engine_mod
        from mochi_server.events import ChatSendData, ToolCallEndData, ToolCallStartData

        monkeypatch.setattr(engine_mod, "_PARK_RETRY_MS", 0)
        sender = FakeSender()
        manager = RunManager(_agent(), sender)
        engine = AttentionEngine(AttentionSettings(), clock=lambda: 1_000)
        coordinator = CompanionCoordinator(engine, manager, sender, ask_expiry_checker=False)
        manager.attach_coordinator(coordinator)

        async def failing_run(ctx):  # type: ignore[no-untyped-def]
            from mochi_server.events import TextEndData, TextStartData

            yield (
                "tool.call.start",
                ToolCallStartData(run_id=ctx.run_id, tool_call_id="tc", name="bash", args={}),
            )
            yield (
                "tool.call.end",
                ToolCallEndData(run_id=ctx.run_id, tool_call_id="tc", status="error", error=None),
            )
            yield "text.start", TextStartData(run_id=ctx.run_id, message_id="m")
            yield "text.end", TextEndData(run_id=ctx.run_id, message_id="m", full_text="失败")

        class FailingAgent:
            def run(self, ctx):  # type: ignore[no-untyped-def]
                return failing_run(ctx)

            async def post_run_events(self, ctx):  # type: ignore[no-untyped-def]
                return []

        manager._agent_source = lambda: FailingAgent()  # type: ignore[method-assign]
        for i in range(2):
            await manager.start_run(ChatSendData(run_id=f"r{i}", session_id="s", text="跑"))
            await _drain(manager)
            # run 结束触发 notify_run_active(False) → pump（调度为后台任务）
            for _ in range(50):
                await asyncio.sleep(0)

        intents = [f for f in sender.frames if f["type"] == "companion.intent"]
        assert len(intents) == 1  # 两次失败合并为一次 ask
        assert intents[0]["data"]["kind"] == "tool_failed"


@pytest.mark.parametrize("session_id", ["new-chat", None])
def test_ws_attention_uses_selected_session(tmp_path, monkeypatch, session_id):
    """主动陪伴也跟随所选会话；老客户端仍沿用 default。"""
    from fastapi.testclient import TestClient

    from mochi_server.config import load_config
    from mochi_server.main import create_app

    cfg = load_config(tmp_path / "config.toml")
    cfg.agent.attention = "auto"
    captured = []

    def record_coordinator(*args, **kwargs):
        captured.append(kwargs["session_id"])
        return CompanionCoordinator(*args, **kwargs)

    monkeypatch.setattr("mochi_server.main.CompanionCoordinator", record_coordinator)
    app = create_app(config=cfg)
    url = f"/ws?sessionId={session_id}" if session_id else "/ws"
    with TestClient(app) as client, client.websocket_connect(url) as ws:
        ws.send_json(
            {
                "v": "0.1",
                "type": "hello",
                "id": "1",
                "ts": 0,
                "data": {"versions": ["0.1"], "client": {"name": "t", "version": "0"}},
            }
        )
        assert ws.receive_json()["type"] == "hello_ack"
        assert captured == [session_id or "default"]
