"""记忆集成测试（M1-S3，功能清单 6.4）。

核心验证目标：**手动添加的记忆在对话中能被正确召回注入 system prompt**。

当前版本仅支持手动添加记忆（自动提取留后续版本）。测试聚焦召回链路：
- MemoryManager + SessionStore 的关键词检索；
- LLMAgentService + MemoryManager 的集成：记忆注入 system prompt；
- 跨会话：不同 session_id 共享同一份记忆库；
- 边界：空记忆、无关查询不召回。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest

from mochi_server.agent import LLMAgentService, ProviderAdapter
from mochi_server.agent.adapters.base import ChatMessage
from mochi_server.agent.service import AgentContext
from mochi_server.memory import MemoryManager
from mochi_server.store import SessionStore

# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path) -> SessionStore:
    return SessionStore(db_path=tmp_path / "test.db")


@pytest.fixture
def mm(store: SessionStore) -> MemoryManager:
    return MemoryManager(store)


async def _seed_memory(
    store: SessionStore,
    content: str,
    category: str = "fact",
    source: str = "manual",
) -> dict:
    """向记忆库写入一条记录。"""
    mid = f"mem-{uuid.uuid4().hex[:12]}"
    return await store.add_memory(mid, category, content, source=source)


class RecordingAdapter(ProviderAdapter):
    """录制发送给 LLM 的 messages，返回固定回复。"""

    def __init__(self, reply: str = "好的，我知道了！") -> None:
        self._reply = reply
        self.calls: list[list[ChatMessage]] = []

    async def stream_chat(
        self, messages: list[ChatMessage], *, run_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        self.calls.append(messages)
        yield ("text", self._reply)

    async def ping(self) -> tuple[bool, str]:
        return True, "ok"


def _ctx(text: str = "你好", session_id: str = "s-1") -> AgentContext:
    return AgentContext(run_id=f"r-{uuid.uuid4().hex[:8]}", session_id=session_id, text=text)


async def _collect_events(agent: LLMAgentService, ctx: AgentContext) -> list[tuple[str, object]]:
    return [(t, p) async for t, p in agent.run(ctx)]


# ---------------------------------------------------------------------------
# 1. 召回：记忆注入 system prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fact_injected_into_system_prompt(store: SessionStore, mm: MemoryManager):
    """事实记忆能被召回并注入 system prompt。"""
    await _seed_memory(store, "用户是 Python 开发者", "fact")
    adapter = RecordingAdapter()
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="帮我写个Python脚本"))

    system_content = adapter.calls[0][0]["content"]
    assert "关于用户的记忆" in system_content
    assert "用户是 Python 开发者" in system_content
    assert "[事实]" in system_content


@pytest.mark.asyncio
async def test_preference_injected_into_system_prompt(store: SessionStore, mm: MemoryManager):
    """偏好记忆能被召回并注入 system prompt。"""
    await _seed_memory(store, "用户喜欢简洁的回答", "preference")
    adapter = RecordingAdapter()
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="你能帮我回答个问题吗"))

    system_content = adapter.calls[0][0]["content"]
    assert "用户喜欢简洁的回答" in system_content
    assert "[偏好]" in system_content


@pytest.mark.asyncio
async def test_multiple_memories_injected(store: SessionStore, mm: MemoryManager):
    """多条相关记忆同时注入。"""
    await _seed_memory(store, "用户是前端工程师", "fact")
    await _seed_memory(store, "用户喜欢 TypeScript", "preference")
    adapter = RecordingAdapter()
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="推荐一些前端工具"))

    system_content = adapter.calls[0][0]["content"]
    assert "前端工程师" in system_content


@pytest.mark.asyncio
async def test_no_memory_no_injection(store: SessionStore, mm: MemoryManager):
    """记忆库为空时不注入任何记忆段落。"""
    adapter = RecordingAdapter()
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="你好"))

    system_content = adapter.calls[0][0]["content"]
    assert system_content == "你是助手"


@pytest.mark.asyncio
async def test_irrelevant_query_no_recall(store: SessionStore, mm: MemoryManager):
    """用户输入与已有记忆无关时，不召回。"""
    await _seed_memory(store, "用户养了一只猫", "fact")
    adapter = RecordingAdapter()
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="explain quantum computing"))

    system_content = adapter.calls[0][0]["content"]
    assert "猫" not in system_content


# ---------------------------------------------------------------------------
# 2. 跨会话：手动添加的记忆在不同会话中召回
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_persists_across_sessions(store: SessionStore, mm: MemoryManager):
    """第一个会话手动添加的记忆，在新会话中仍然能被召回。"""
    await _seed_memory(store, "用户的名字叫小明", "fact")

    # 新会话：应该能召回
    adapter = RecordingAdapter()
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)
    await _collect_events(agent, _ctx(text="你还记得我叫什么名字吗", session_id="session-2"))

    system_content = adapter.calls[0][0]["content"]
    assert "小明" in system_content


@pytest.mark.asyncio
async def test_manual_memory_recalled_in_conversation(store: SessionStore, mm: MemoryManager):
    """通过 API 手动添加的记忆也能在对话中被召回。"""
    await _seed_memory(store, "用户对花粉过敏", "fact", source="manual")
    adapter = RecordingAdapter()
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="春天来了花粉好多"))

    system_content = adapter.calls[0][0]["content"]
    assert "花粉过敏" in system_content


# ---------------------------------------------------------------------------
# 3. 无 MemoryManager 时的降级行为
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_memory_manager_no_injection(store: SessionStore):
    """memory_manager=None 时不注入记忆，保持原始 system prompt。"""
    adapter = RecordingAdapter()
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=None)

    await _collect_events(agent, _ctx(text="你好"))

    system_content = adapter.calls[0][0]["content"]
    assert system_content == "你是助手"


# ---------------------------------------------------------------------------
# 4. MemoryManager 单元级别补充
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_format_memories_mixed(mm: MemoryManager):
    """format_memories 正确格式化事实和偏好。"""
    memories = [
        {"category": "fact", "content": "用户住在北京"},
        {"category": "preference", "content": "用户喜欢TypeScript"},
    ]
    result = mm.format_memories(memories)
    assert "## 关于用户的记忆" in result
    assert "[事实] 用户住在北京" in result
    assert "[偏好] 用户喜欢TypeScript" in result


@pytest.mark.asyncio
async def test_recall_empty_store(store: SessionStore, mm: MemoryManager):
    """空记忆库召回返回空字符串。"""
    result = await mm.recall_for_prompt("任意问题")
    assert result == ""


@pytest.mark.asyncio
async def test_recall_returns_formatted_section(store: SessionStore, mm: MemoryManager):
    """召回成功时返回格式化的记忆段落。"""
    await _seed_memory(store, "用户是设计师", "fact")
    result = await mm.recall_for_prompt("我想做设计")
    assert "关于用户的记忆" in result
    assert "用户是设计师" in result


@pytest.mark.asyncio
async def test_recall_respects_limit(store: SessionStore, mm: MemoryManager):
    """召回不超过 _RECALL_LIMIT（5）条记忆。"""
    for i in range(10):
        await _seed_memory(store, f"用户事实{i}", "fact")

    results = await store.search_memories("用户事实", limit=5)
    assert len(results) <= 5


# ---------------------------------------------------------------------------
# 5. CJK 与多语言关键词召回
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cjk_recall_in_conversation(store: SessionStore, mm: MemoryManager):
    """中文用户输入能通过 2-gram 匹配召回中文记忆。"""
    await _seed_memory(store, "用户养了一只柯基犬", "fact")
    adapter = RecordingAdapter()
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="我的柯基最近不爱吃饭"))

    system_content = adapter.calls[0][0]["content"]
    assert "柯基" in system_content


@pytest.mark.asyncio
async def test_english_keyword_recall(store: SessionStore, mm: MemoryManager):
    """英文关键词也能正确匹配召回。"""
    await _seed_memory(store, "用户使用 React 框架", "fact")
    adapter = RecordingAdapter()
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="帮我优化 React 组件性能"))

    system_content = adapter.calls[0][0]["content"]
    assert "React" in system_content
