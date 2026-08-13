"""记忆集成测试（M1-S3，功能清单 6.4）。

核心验证目标：**每个对话回合都能带上新加的事实和偏好去回答用户的问题**。

测试层级：
- MemoryManager + SessionStore 的召回/沉淀端到端流程；
- LLMAgentService + MemoryManager 的集成：记忆注入 system prompt、自动沉淀；
- 跨会话：不同 session_id 共享同一份记忆库；
- 边界：空记忆、无关查询不召回、重复记忆去重、异常降级。
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
    """录制发送给 LLM 的 messages，返回固定回复；支持自定义 extract 回复。"""

    def __init__(
        self,
        reply: str = "好的，我知道了！",
        extract_reply: str = "[]",
    ) -> None:
        self._reply = reply
        self._extract_reply = extract_reply
        self.calls: list[list[ChatMessage]] = []

    async def stream_chat(
        self, messages: list[ChatMessage], *, run_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        self.calls.append(messages)
        # 记忆提取调用（run_id="memory-extract"）返回 extract_reply
        text = self._extract_reply if run_id == "memory-extract" else self._reply
        yield ("text", text)

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

    # 第一次调用是正式对话（非 memory-extract）
    main_call = adapter.calls[0]
    system_content = main_call[0]["content"]
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

    main_call = adapter.calls[0]
    system_content = main_call[0]["content"]
    assert "用户喜欢简洁的回答" in system_content
    assert "[偏好]" in system_content


@pytest.mark.asyncio
async def test_multiple_memories_injected(store: SessionStore, mm: MemoryManager):
    """多条相关记忆同时注入。"""
    await _seed_memory(store, "用户是前端工程师", "fact")
    await _seed_memory(store, "用户喜欢 TypeScript", "preference")
    await _seed_memory(store, "用户在北京工作", "fact")
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
    assert "关于用户的记忆" not in system_content
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
# 2. 沉淀：对话后自动提取记忆
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_extract_stores_new_memory(store: SessionStore, mm: MemoryManager):
    """对话完成后 LLM 提取的记忆自动落盘。"""
    extract_json = '[{"category": "fact", "content": "用户养了两只猫"}]'
    adapter = RecordingAdapter(extract_reply=extract_json)
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="我家有两只猫"))

    memories = await store.list_memories()
    assert len(memories) == 1
    assert memories[0]["content"] == "用户养了两只猫"
    assert memories[0]["category"] == "fact"
    assert memories[0]["source"] == "auto"


@pytest.mark.asyncio
async def test_auto_extract_preference(store: SessionStore, mm: MemoryManager):
    """自动提取的偏好记忆正确落盘。"""
    extract_json = '[{"category": "preference", "content": "用户偏好深色模式"}]'
    adapter = RecordingAdapter(extract_reply=extract_json)
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="我更喜欢深色模式"))

    memories = await store.list_memories(category="preference")
    assert len(memories) == 1
    assert memories[0]["content"] == "用户偏好深色模式"


@pytest.mark.asyncio
async def test_auto_extract_empty_array_no_store(store: SessionStore, mm: MemoryManager):
    """LLM 返回空数组时不写入任何记忆。"""
    adapter = RecordingAdapter(extract_reply="[]")
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="今天天气怎么样"))

    memories = await store.list_memories()
    assert len(memories) == 0


@pytest.mark.asyncio
async def test_auto_extract_dedup(store: SessionStore, mm: MemoryManager):
    """已有相同内容的记忆不重复写入。"""
    await _seed_memory(store, "用户是 Python 开发者", "fact")
    extract_json = '[{"category": "fact", "content": "用户是 Python 开发者"}]'
    adapter = RecordingAdapter(extract_reply=extract_json)
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="我用 Python 开发"))

    memories = await store.list_memories()
    assert len(memories) == 1  # 未新增重复记忆


@pytest.mark.asyncio
async def test_auto_extract_multiple_items(store: SessionStore, mm: MemoryManager):
    """单次对话提取多条记忆全部落盘。"""
    extract_json = (
        '[{"category": "fact", "content": "用户住在上海"},'
        ' {"category": "preference", "content": "用户喜欢喝咖啡"}]'
    )
    adapter = RecordingAdapter(extract_reply=extract_json)
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="我住在上海，平时爱喝咖啡"))

    memories = await store.list_memories()
    assert len(memories) == 2
    contents = {m["content"] for m in memories}
    assert "用户住在上海" in contents
    assert "用户喜欢喝咖啡" in contents


@pytest.mark.asyncio
async def test_auto_extract_invalid_json_silent(store: SessionStore, mm: MemoryManager):
    """LLM 返回无效 JSON 时静默降级，不写入记忆，不抛异常。"""
    adapter = RecordingAdapter(extract_reply="这不是JSON啊")
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="你好"))

    memories = await store.list_memories()
    assert len(memories) == 0


@pytest.mark.asyncio
async def test_auto_extract_markdown_fenced(store: SessionStore, mm: MemoryManager):
    """LLM 返回带 markdown 围栏的 JSON 也能正确解析。"""
    extract_json = '```json\n[{"category": "fact", "content": "用户会弹吉他"}]\n```'
    adapter = RecordingAdapter(extract_reply=extract_json)
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="我平时喜欢弹吉他"))

    memories = await store.list_memories()
    assert len(memories) == 1
    assert memories[0]["content"] == "用户会弹吉他"


# ---------------------------------------------------------------------------
# 3. 跨会话/跨回合：记忆持久性
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_persists_across_sessions(store: SessionStore, mm: MemoryManager):
    """第一个会话存入的记忆，在新会话中仍然能被召回。"""
    # 第一个会话：产生记忆
    extract_json = '[{"category": "fact", "content": "用户的名字叫小明"}]'
    adapter = RecordingAdapter(extract_reply=extract_json)
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)
    await _collect_events(agent, _ctx(text="我叫小明", session_id="session-1"))

    # 验证记忆已落盘
    memories = await store.list_memories()
    assert any(m["content"] == "用户的名字叫小明" for m in memories)

    # 第二个会话：应该能召回
    adapter2 = RecordingAdapter(extract_reply="[]")
    agent2 = LLMAgentService(adapter2, system_prompt="你是助手", store=store, memory_manager=mm)
    await _collect_events(agent2, _ctx(text="你还记得我叫什么名字吗", session_id="session-2"))

    system_content = adapter2.calls[0][0]["content"]
    assert "小明" in system_content


@pytest.mark.asyncio
async def test_memory_persists_across_turns(store: SessionStore, mm: MemoryManager):
    """同一会话的后续回合也能召回之前自动提取的记忆。"""
    # 第一回合：自动提取记忆
    extract_json = '[{"category": "preference", "content": "用户喜欢用Vim"}]'
    adapter = RecordingAdapter(reply="好的！", extract_reply=extract_json)
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)
    await _collect_events(agent, _ctx(text="我一直用Vim写代码", session_id="s-1"))

    # 第二回合：用户输入包含"Vim"关键词，应触发召回
    adapter2 = RecordingAdapter(extract_reply="[]")
    agent2 = LLMAgentService(adapter2, system_prompt="你是助手", store=store, memory_manager=mm)
    await _collect_events(agent2, _ctx(text="Vim有什么好用的插件", session_id="s-1"))

    # "Vim" 关键词应触发召回
    system_content = adapter2.calls[0][0]["content"]
    assert "Vim" in system_content


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
# 4. 无 MemoryManager 时的降级行为
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_memory_manager_no_injection(store: SessionStore):
    """memory_manager=None 时不注入记忆，保持原始 system prompt。"""
    adapter = RecordingAdapter()
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=None)

    await _collect_events(agent, _ctx(text="你好"))

    system_content = adapter.calls[0][0]["content"]
    assert system_content == "你是助手"


@pytest.mark.asyncio
async def test_no_memory_manager_no_extract(store: SessionStore):
    """memory_manager=None 时不执行记忆提取，记忆库保持为空。"""
    adapter = RecordingAdapter(extract_reply='[{"category": "fact", "content": "不该出现"}]')
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=None)

    await _collect_events(agent, _ctx(text="你好"))

    # extract 调用不应被执行，只有 1 次 main call
    assert len(adapter.calls) == 1
    memories = await store.list_memories()
    assert len(memories) == 0


# ---------------------------------------------------------------------------
# 5. MemoryManager 单元级别补充
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
async def test_extract_invalid_category_falls_back(store: SessionStore, mm: MemoryManager):
    """LLM 返回非法 category 时回退为 fact。"""
    extract_json = '[{"category": "mood", "content": "用户今天心情好"}]'
    adapter = RecordingAdapter(extract_reply=extract_json)
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="我今天心情好"))

    memories = await store.list_memories()
    assert len(memories) == 1
    assert memories[0]["category"] == "fact"  # 回退为 fact


@pytest.mark.asyncio
async def test_extract_empty_content_skipped(store: SessionStore, mm: MemoryManager):
    """LLM 提取的空内容记忆被跳过。"""
    extract_json = (
        '[{"category": "fact", "content": ""}, {"category": "fact", "content": "有效记忆"}]'
    )
    adapter = RecordingAdapter(extract_reply=extract_json)
    agent = LLMAgentService(adapter, system_prompt="你是助手", store=store, memory_manager=mm)

    await _collect_events(agent, _ctx(text="你好"))

    memories = await store.list_memories()
    assert len(memories) == 1
    assert memories[0]["content"] == "有效记忆"


# ---------------------------------------------------------------------------
# 6. 记忆召回上限
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_respects_limit(store: SessionStore, mm: MemoryManager):
    """召回不超过 _RECALL_LIMIT（5）条记忆。"""
    for i in range(10):
        await _seed_memory(store, f"用户事实{i}", "fact")

    # search_memories 默认 limit=5
    results = await store.search_memories("用户事实", limit=5)
    assert len(results) <= 5


# ---------------------------------------------------------------------------
# 7. CJK 与多语言关键词召回
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
