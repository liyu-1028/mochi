"""MemoryStore 测试（M1-S3，功能清单 6.4）：CRUD + FTS5 检索。"""

from __future__ import annotations

import uuid

import pytest

from mochi_server.store import SessionStore


@pytest.fixture
def store(tmp_path) -> SessionStore:
    return SessionStore(db_path=tmp_path / "test.db")


async def _add(
    store: SessionStore, content: str, category: str = "fact", mid: str | None = None
) -> dict:
    return await store.add_memory(
        mid or f"mem-{uuid.uuid4().hex[:8]}", category, content, source="auto"
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_and_list(store: SessionStore):
    await _add(store, "用户是 Python 开发者", "fact")
    await _add(store, "用户喜欢简洁的回答", "preference")
    items = await store.list_memories()
    assert len(items) == 2
    contents = {m["content"] for m in items}
    assert "用户是 Python 开发者" in contents
    assert "用户喜欢简洁的回答" in contents


@pytest.mark.asyncio
async def test_list_by_category(store: SessionStore):
    await _add(store, "fact-1", "fact")
    await _add(store, "pref-1", "preference")
    facts = await store.list_memories(category="fact")
    assert len(facts) == 1
    assert facts[0]["category"] == "fact"


@pytest.mark.asyncio
async def test_update_memory(store: SessionStore):
    await _add(store, "旧内容", mid="mem-edit")
    updated = await store.update_memory("mem-edit", "新内容")
    assert updated is not None
    assert updated["content"] == "新内容"
    assert updated["createdAt"] <= updated["updatedAt"]


@pytest.mark.asyncio
async def test_update_nonexistent(store: SessionStore):
    assert await store.update_memory("nope", "x") is None


@pytest.mark.asyncio
async def test_delete_memory(store: SessionStore):
    await _add(store, "to delete", mid="mem-del")
    assert await store.delete_memory("mem-del") is True
    assert await store.delete_memory("mem-del") is False  # 重复删除
    items = await store.list_memories()
    assert len(items) == 0


@pytest.mark.asyncio
async def test_clear_all(store: SessionStore):
    await _add(store, "a")
    await _add(store, "b")
    count = await store.clear_all_memories()
    assert count == 2
    assert await store.list_memories() == []


# ---------------------------------------------------------------------------
# FTS5 搜索
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_basic(store: SessionStore):
    await _add(store, "用户是一名前端工程师")
    await _add(store, "用户喜欢深色模式")
    results = await store.search_memories("前端")
    assert len(results) >= 1
    assert "前端" in results[0]["content"]


@pytest.mark.asyncio
async def test_search_keyword_match(store: SessionStore):
    """用户输入整句包含记忆关键词时命中（核心召回场景）。"""
    await _add(store, "用户是Python开发者")
    # 模拟真实用户输入：整句包含 Python 关键词
    results = await store.search_memories("帮我写个Python脚本")
    assert len(results) >= 1
    assert "Python" in results[0]["content"]


@pytest.mark.asyncio
async def test_search_cjk_bigram(store: SessionStore):
    """中文 2-gram 匹配：用户输入与记忆共享两字相邻片段时命中。"""
    await _add(store, "用户养了一只猫")
    results = await store.search_memories("我家的小猫生病了")
    assert len(results) >= 1
    assert "猫" in results[0]["content"]


@pytest.mark.asyncio
async def test_search_no_match(store: SessionStore):
    await _add(store, "用户喜欢猫")
    results = await store.search_memories("quantum physics problem")
    assert results == []


@pytest.mark.asyncio
async def test_search_empty_query(store: SessionStore):
    await _add(store, "something")
    assert await store.search_memories("") == []
    assert await store.search_memories("   ") == []
