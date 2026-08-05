"""多轮上下文与历史回看测试：拼装、落盘、REST 回看（真实 HTTP 层）。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from mochi_server.agent import LLMAgentService, ProviderAdapter
from mochi_server.agent.adapters.base import ChatMessage
from mochi_server.agent.echo_agent import EchoAgentService
from mochi_server.agent.llm_agent import DEFAULT_SYSTEM_PROMPT
from mochi_server.agent.service import AgentContext
from mochi_server.config import AppConfig, ModelConfig
from mochi_server.events import PROTOCOL_VERSION
from mochi_server.main import create_app
from mochi_server.store import SessionStore


class _RecordingAdapter(ProviderAdapter):
    """记录收到的 messages，供断言多轮拼装。"""

    def __init__(self, reply: str = "收到") -> None:
        self._reply = reply
        self.last_messages: list[ChatMessage] | None = None

    async def stream_chat(
        self, messages: list[ChatMessage], *, run_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        self.last_messages = messages
        yield "text", self._reply

    async def ping(self) -> tuple[bool, str]:
        return True, "ok"


@pytest.mark.asyncio
async def test_multi_turn_assembles_history_before_current_user(tmp_path) -> None:
    store = SessionStore(db_path=tmp_path / "t.db")
    try:
        await store.append_message("s-1", "user", "我叫小明")
        await store.append_message("s-1", "assistant", "你好小明！")
        adapter = _RecordingAdapter()
        agent = LLMAgentService(adapter, store=store)
        ctx = AgentContext(run_id="r-1", session_id="s-1", text="你还记得我叫什么吗")
        async for _ in agent.run(ctx):
            pass
        assert adapter.last_messages == [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": "我叫小明"},
            {"role": "assistant", "content": "你好小明！"},
            {"role": "user", "content": "你还记得我叫什么吗"},
        ]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_turn_is_persisted_after_completion(tmp_path) -> None:
    store = SessionStore(db_path=tmp_path / "t.db")
    try:
        agent = LLMAgentService(_RecordingAdapter("我记得你叫小明"), store=store)
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
    adapter = _RecordingAdapter()
    agent = LLMAgentService(adapter)  # store=None
    ctx = AgentContext(run_id="r-1", session_id="s-1", text="你好")
    async for _ in agent.run(ctx):
        pass
    assert adapter.last_messages is not None
    assert len(adapter.last_messages) == 2  # system + user，无历史


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
