"""SessionStore 测试：迁移幂等、消息落盘、历史取序、会话管理。"""

from __future__ import annotations

import pytest

from mochi_server.store import SessionStore


async def _append(store: SessionStore, session_id: str, *pairs: tuple[str, str]) -> None:
    for role, content in pairs:
        await store.append_message(session_id, role, content)


@pytest.mark.asyncio
async def test_append_creates_session_and_backfills_title(tmp_path) -> None:
    store = SessionStore(db_path=tmp_path / "t.db")
    try:
        await _append(store, "s-1", ("user", "你好，我是小明"), ("assistant", "嗨小明"))
        sessions = await store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == "s-1"
        assert sessions[0]["title"] == "你好，我是小明"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_title_truncated_to_max_chars(tmp_path) -> None:
    store = SessionStore(db_path=tmp_path / "t.db")
    try:
        long_text = "长" * 100
        await _append(store, "s-1", ("user", long_text))
        sessions = await store.list_sessions()
        assert sessions[0]["title"] == "长" * 30
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_recent_messages_returns_chronological_and_respects_limit(tmp_path) -> None:
    store = SessionStore(db_path=tmp_path / "t.db")
    try:
        # 连续快速写入（ts 可能同毫秒），验证 id 兜底排序仍正确
        await _append(
            store,
            "s-1",
            ("user", "第1句"),
            ("assistant", "第2句"),
            ("user", "第3句"),
            ("assistant", "第4句"),
        )
        recent = await store.recent_messages("s-1", limit=2)
        assert [m["content"] for m in recent] == ["第3句", "第4句"]
        full = await store.get_messages("s-1")
        assert [m["content"] for m in full] == ["第1句", "第2句", "第3句", "第4句"]
        assert [m["role"] for m in full] == ["user", "assistant", "user", "assistant"]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_sessions_are_isolated(tmp_path) -> None:
    store = SessionStore(db_path=tmp_path / "t.db")
    try:
        await _append(store, "s-a", ("user", "A 会话"))
        await _append(store, "s-b", ("user", "B 会话"))
        assert [m["content"] for m in await store.get_messages("s-a")] == ["A 会话"]
        assert [m["content"] for m in await store.get_messages("s-b")] == ["B 会话"]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_list_sessions_ordered_by_recent_activity(tmp_path) -> None:
    store = SessionStore(db_path=tmp_path / "t.db")
    try:
        await _append(store, "old", ("user", "较早的会话"))
        await _append(store, "new", ("user", "较晚的会话"))
        await _append(store, "old", ("assistant", "让 old 重新活跃"))
        sessions = await store.list_sessions()
        assert [s["id"] for s in sessions] == ["old", "new"]
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_delete_session_removes_messages_and_is_idempotent(tmp_path) -> None:
    store = SessionStore(db_path=tmp_path / "t.db")
    try:
        await _append(store, "s-1", ("user", "要删的"), ("assistant", "好的"))
        assert await store.delete_session("s-1") is True
        assert await store.get_messages("s-1") == []
        assert await store.list_sessions() == []
        assert await store.delete_session("s-1") is False  # 幂等
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_migration_is_idempotent_across_reopen(tmp_path) -> None:
    db_path = tmp_path / "t.db"
    store = SessionStore(db_path=db_path)
    try:
        await _append(store, "s-1", ("user", "持久化检查"))
    finally:
        await store.close()
    # 重新打开同一文件：迁移不应重复执行或报错，数据仍在
    reopened = SessionStore(db_path=db_path)
    try:
        assert [m["content"] for m in await reopened.get_messages("s-1")] == ["持久化检查"]
    finally:
        await reopened.close()
