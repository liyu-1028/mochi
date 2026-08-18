"""多轮上下文与历史回看测试：拼装、落盘、REST 回看（真实 HTTP 层）。"""

from __future__ import annotations

import pytest
from fakes import ScriptedChatModel, make_test_adapter
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from mochi_server.agent import LLMAgentService
from mochi_server.agent.echo_agent import EchoAgentService
from mochi_server.agent.llm_agent import DEFAULT_SYSTEM_PROMPT
from mochi_server.agent.service import AgentContext
from mochi_server.config import AppConfig, ModelConfig
from mochi_server.events import PROTOCOL_VERSION
from mochi_server.main import create_app
from mochi_server.store import SessionStore


def _recording_agent(reply: str = "收到", *, store: SessionStore | None = None):
    """固定回复假模型 + 录制收到的消息（M1-S4 图内核路径）。"""
    model = ScriptedChatModel(calls=[[AIMessageChunk(content=reply)]])
    return LLMAgentService(make_test_adapter(model), store=store), model


@pytest.mark.asyncio
async def test_multi_turn_assembles_history_before_current_user(tmp_path) -> None:
    store = SessionStore(db_path=tmp_path / "t.db")
    try:
        await store.append_message("s-1", "user", "我叫小明")
        await store.append_message("s-1", "assistant", "你好小明！")
        agent, model = _recording_agent(store=store)
        ctx = AgentContext(run_id="r-1", session_id="s-1", text="你还记得我叫什么吗")
        async for _ in agent.run(ctx):
            pass
        # 图内消息会由 langgraph 分配 id，按类型+内容断言
        assert [(type(m).__name__, m.content) for m in model.received[0]] == [
            ("SystemMessage", DEFAULT_SYSTEM_PROMPT),
            ("HumanMessage", "我叫小明"),
            ("AIMessage", "你好小明！"),
            ("HumanMessage", "你还记得我叫什么吗"),
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_turn_is_persisted_after_completion(tmp_path) -> None:
    store = SessionStore(db_path=tmp_path / "t.db")
    try:
        agent, _ = _recording_agent("我记得你叫小明", store=store)
        ctx = AgentContext(run_id="r-1", session_id="s-1", text="你好")
        async for _ in agent.run(ctx):
            pass
        msgs = await store.get_messages("s-1")
        assert [(m["role"], m["content"]) for m in msgs] == [
            ("user", "你好"),
            ("assistant", "我记得你叫小明"),
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_no_store_keeps_single_turn_behavior(tmp_path) -> None:
    """向后兼容：不注入 store 时不读不写，行为等同 M0。"""
    agent, model = _recording_agent()  # store=None
    ctx = AgentContext(run_id="r-1", session_id="s-1", text="你好")
    async for _ in agent.run(ctx):
        pass
    assert model.received[0] is not None
    assert len(model.received[0]) == 2  # system + user，无历史


@pytest.mark.asyncio
async def test_echo_agent_persists_when_store_injected(tmp_path) -> None:
    store = SessionStore(db_path=tmp_path / "t.db")
    try:
        agent = EchoAgentService(chunk_delay=0, thinking_delay=0, store=store)
        ctx = AgentContext(run_id="r-1", session_id="s-echo", text="在吗")
        async for _ in agent.run(ctx):
            pass
        msgs = await store.get_messages("s-echo")
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "在吗"
        assert msgs[1]["role"] == "assistant"
        assert msgs[0]["ts"] > 0
    finally:
        await store.close()


# ---------------------------------------------------------------------------
# REST 回看（真实 HTTP 层，经 trial 模式 echo 落盘）
# ---------------------------------------------------------------------------


def _hello() -> dict:
    return {
        "v": PROTOCOL_VERSION,
        "type": "hello",
        "id": "c-hello",
        "ts": 0,
        "data": {"versions": [PROTOCOL_VERSION], "client": {"name": "pytest", "version": "0"}},
    }


def _chat_send(run_id: str, text: str, session_id: str = "default") -> dict:
    return {
        "v": PROTOCOL_VERSION,
        "type": "chat.send",
        "id": "c-send",
        "ts": 0,
        "data": {"runId": run_id, "sessionId": session_id, "text": text},
    }


def _drain_until_finished(ws, limit: int = 300) -> list[dict]:
    frames = []
    for _ in range(limit):
        frame = ws.receive_json()
        frames.append(frame)
        if frame["type"] == "run.finished":
            return frames
    raise AssertionError("超过帧数上限仍未收到 run.finished")


def test_ws_turns_persist_and_rest_reads_back() -> None:
    config = AppConfig(model=ModelConfig(default_provider="trial", providers={}))
    with TestClient(create_app(config=config)) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json(_hello())
            ws.receive_json()  # hello_ack
            ws.send_json(_chat_send("r-1", "第一句"))
            _drain_until_finished(ws)
            ws.send_json(_chat_send("r-2", "第二句"))
            _drain_until_finished(ws)

        sessions = client.get("/sessions")
        assert sessions.status_code == 200
        body = sessions.json()
        assert len(body) == 1
        assert body[0]["id"] == "default"
        assert body[0]["title"] == "第一句"

        msgs = client.get("/sessions/default/messages")
        assert msgs.status_code == 200
        roles = [m["role"] for m in msgs.json()]
        assert roles == ["user", "assistant", "user", "assistant"]

        delete = client.delete("/sessions/default")
        assert delete.status_code == 204
        assert client.get("/sessions").json() == []
