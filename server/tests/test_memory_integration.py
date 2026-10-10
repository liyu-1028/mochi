"""记忆集成测试（M1-S3，功能清单 6.4）。

核心验证目标：**手动添加的记忆在对话中能被正确召回注入 system prompt**。

测试聚焦手动/自动记忆的持久化和召回链路：
- MemoryManager + SessionStore 的关键词检索；
- LLMAgentService + MemoryManager 的集成：记忆注入 system prompt；
- 跨会话：不同 session_id 共享同一份记忆库；
- 边界：空记忆、上下文预算、编辑与删除后即时生效。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fakes import ScriptedChatModel, make_test_adapter
from langchain_core.messages import AIMessageChunk

from mochi_server.agent import LLMAgentService
from mochi_server.agent.llm_agent import reply_length_requirement
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


def _recording_agent(
    store: SessionStore, memory_manager: MemoryManager | None, reply: str = "好的，我知道了！"
) -> tuple[LLMAgentService, ScriptedChatModel]:
    """固定回复的假模型 + 录制收到的消息（M1-S4 图内核路径）。

    第二剧本对应 6.4 自动沉淀的后台提取调用（返回空数组，不产生记忆），
    避免 fire-and-forget 耗尽剧本报错。
    """
    model = ScriptedChatModel(
        calls=[[AIMessageChunk(content=reply)], [AIMessageChunk(content="[]")]]
    )
    agent = LLMAgentService(
        make_test_adapter(model),
        system_prompt="你是助手",
        store=store,
        memory_manager=memory_manager,
    )
    return agent, model


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
    agent, model = _recording_agent(store, mm)
    await _collect_events(agent, _ctx(text="帮我写个Python脚本"))

    system_content = model.received[0][0].content
    assert "关于用户的记忆" in system_content
    assert "用户是 Python 开发者" in system_content
    assert "[事实]" in system_content


@pytest.mark.asyncio
async def test_preference_injected_into_system_prompt(store: SessionStore, mm: MemoryManager):
    """偏好记忆能被召回并注入 system prompt。"""
    await _seed_memory(store, "用户喜欢简洁的回答", "preference")
    agent, model = _recording_agent(store, mm)
    await _collect_events(agent, _ctx(text="你能帮我回答个问题吗"))

    system_content = model.received[0][0].content
    assert "用户喜欢简洁的回答" in system_content
    assert "[偏好]" in system_content


@pytest.mark.asyncio
async def test_manual_preference_recalled_without_repeating_its_keywords(
    store: SessionStore, mm: MemoryManager
):
    """用户只问偏好，不能要求先说出偏好内容才能召回。"""
    content = "我需要你的回答比较活泼和幽默。"
    await _seed_memory(store, content, "preference")
    agent, model = _recording_agent(store, mm)
    await _collect_events(agent, _ctx(text="我的个人偏好是什么？", session_id="new-session"))

    assert content in model.received[0][0].content


@pytest.mark.asyncio
async def test_preferences_apply_to_unrelated_requests(store: SessionStore, mm: MemoryManager):
    await _seed_memory(store, "回答要活泼幽默", "preference", source="auto")
    agent, model = _recording_agent(store, mm)
    await _collect_events(agent, _ctx(text="explain quantum computing"))
    assert "回答要活泼幽默" in model.received[0][0].content


@pytest.mark.asyncio
async def test_old_manual_preference_survives_newer_facts(store: SessionStore, mm: MemoryManager):
    await _seed_memory(store, "回答要活泼幽默", "preference")
    for i in range(25):
        await _seed_memory(store, f"最近的项目编号 {i}", source="auto")
    agent, model = _recording_agent(store, mm)
    await _collect_events(agent, _ctx(text="说说我的偏好"))
    assert "回答要活泼幽默" in model.received[0][0].content


@pytest.mark.asyncio
async def test_manual_memory_api_persists_and_is_used_after_restart():
    from fastapi.testclient import TestClient

    from mochi_server.config import AppConfig
    from mochi_server.main import create_app

    with TestClient(create_app(config=AppConfig())) as client:
        preference = client.post(
            "/memories", json={"category": "preference", "content": "回答要活泼幽默"}
        ).json()
        fact = client.post("/memories", json={"category": "fact", "content": "昵称是松子"}).json()

    with TestClient(create_app(config=AppConfig())) as restarted:
        assert {m["id"] for m in restarted.get("/memories").json()} == {
            preference["id"],
            fact["id"],
        }
        store = SessionStore()
        try:
            mm = MemoryManager(store, auto_extract=False)
            agent, model = _recording_agent(store, mm)
            await _collect_events(agent, _ctx(text="你知道我的哪些信息？"))
            assert "回答要活泼幽默" in model.received[0][0].content
            assert "昵称是松子" in model.received[0][0].content

            restarted.put(f"/memories/{preference['id']}", json={"content": "回答要简洁严谨"})
            restarted.delete(f"/memories/{fact['id']}")
            recalled = await mm.recall_for_prompt("我的个人偏好是什么？")
            assert "回答要简洁严谨" in recalled
            assert "回答要活泼幽默" not in recalled
            assert "昵称是松子" not in recalled
            restarted.delete("/memories")
            assert await mm.recall_for_prompt("我的个人偏好是什么？") == ""
        finally:
            await store.close()


@pytest.mark.asyncio
async def test_multiple_memories_injected(store: SessionStore, mm: MemoryManager):
    """多条相关记忆同时注入。"""
    await _seed_memory(store, "用户是前端工程师", "fact")
    await _seed_memory(store, "用户喜欢 TypeScript", "preference")
    agent, model = _recording_agent(store, mm)
    await _collect_events(agent, _ctx(text="推荐一些前端工具"))

    system_content = model.received[0][0].content
    assert "前端工程师" in system_content


@pytest.mark.asyncio
async def test_no_memory_no_injection(store: SessionStore, mm: MemoryManager):
    """记忆库为空时不注入任何记忆段落。"""
    agent, model = _recording_agent(store, mm)
    await _collect_events(agent, _ctx(text="你好"))

    system_content = model.received[0][0].content
    # 回复长度硬性要求后缀恒在（reply_length_requirement），记忆段落则不注入
    assert system_content == "你是助手" + reply_length_requirement(200)


@pytest.mark.asyncio
async def test_user_facts_remain_available_without_keyword_overlap(
    store: SessionStore, mm: MemoryManager
):
    """小规模用户背景不依赖问题字面匹配，模型可据内容自行判断相关性。"""
    await _seed_memory(store, "用户养了一只猫", "fact")
    agent, model = _recording_agent(store, mm)
    await _collect_events(agent, _ctx(text="explain quantum computing"))

    system_content = model.received[0][0].content
    assert "用户养了一只猫" in system_content


# ---------------------------------------------------------------------------
# 2. 跨会话：手动添加的记忆在不同会话中召回
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_persists_across_sessions(store: SessionStore, mm: MemoryManager):
    """第一个会话手动添加的记忆，在新会话中仍然能被召回。"""
    await _seed_memory(store, "用户的名字叫小明", "fact")

    # 新会话：应该能召回
    agent, model = _recording_agent(store, mm)
    await _collect_events(agent, _ctx(text="你还记得我叫什么名字吗", session_id="session-2"))

    system_content = model.received[0][0].content
    assert "小明" in system_content


@pytest.mark.asyncio
async def test_manual_memory_recalled_in_conversation(store: SessionStore, mm: MemoryManager):
    """通过 API 手动添加的记忆也能在对话中被召回。"""
    await _seed_memory(store, "用户对花粉过敏", "fact", source="manual")
    agent, model = _recording_agent(store, mm)
    await _collect_events(agent, _ctx(text="春天来了花粉好多"))

    system_content = model.received[0][0].content
    assert "花粉过敏" in system_content


# ---------------------------------------------------------------------------
# 3. 无 MemoryManager 时的降级行为
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_memory_manager_no_injection(store: SessionStore):
    """memory_manager=None 时不注入记忆，保持原始 system prompt。"""
    agent, model = _recording_agent(store, None)
    await _collect_events(agent, _ctx(text="你好"))

    system_content = model.received[0][0].content
    # 回复长度硬性要求后缀恒在（reply_length_requirement），记忆段落则不注入
    assert system_content == "你是助手" + reply_length_requirement(200)


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
    """用户背景与关键词召回合并后仍限制条数，且不重复注入。"""
    for i in range(30):
        await _seed_memory(store, f"用户事实{i}", "fact")

    result = await mm.recall_for_prompt("用户事实")
    lines = [line for line in result.splitlines() if line.startswith("- [")]
    assert len(lines) == 20
    assert len(set(lines)) == 20


@pytest.mark.asyncio
async def test_recall_character_budget_keeps_whole_memories(store: SessionStore, mm: MemoryManager):
    for i in range(10):
        await _seed_memory(store, f"偏好{i}：" + "简洁" * 40, "preference")
    result = await mm.recall_for_prompt("我的个人偏好是什么？", max_chars=400)
    assert result
    assert len(result) <= 400
    assert all(line.endswith("简洁" * 40) for line in result.splitlines() if line.startswith("- ["))
    assert await mm.recall_for_prompt("我的个人偏好是什么？", max_chars=0) == ""


@pytest.mark.asyncio
async def test_related_older_fact_fits_alongside_user_profile(
    store: SessionStore, mm: MemoryManager
):
    await _seed_memory(store, "项目的代号是 AmberCity", source="auto")
    for i in range(25):
        await _seed_memory(store, f"第{i}个回答偏好", "preference")
    assert "项目的代号是 AmberCity" in await mm.recall_for_prompt("AmberCity")


@pytest.mark.asyncio
async def test_memory_obeys_small_model_context_window(store: SessionStore, mm: MemoryManager):
    from mochi_server.agent.context import estimate_messages_tokens

    for i in range(30):
        await _seed_memory(store, f"用户偏好{i}：" + "简洁" * 200, "preference")
    model = ScriptedChatModel(calls=[[AIMessageChunk(content="好")]])
    agent = LLMAgentService(
        make_test_adapter(model),
        system_prompt="你是助手",
        store=store,
        memory_manager=MemoryManager(store, auto_extract=False),
        context_window=512,
    )
    await _collect_events(agent, _ctx(text="我的个人偏好是什么？"))
    messages = [{"role": "system", "content": m.content} for m in model.received[0]]
    assert estimate_messages_tokens(messages) < 512


# ---------------------------------------------------------------------------
# 5. CJK 与多语言关键词召回
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cjk_recall_in_conversation(store: SessionStore, mm: MemoryManager):
    """中文用户输入能通过 2-gram 匹配召回中文记忆。"""
    await _seed_memory(store, "用户养了一只柯基犬", "fact")
    agent, model = _recording_agent(store, mm)
    await _collect_events(agent, _ctx(text="我的柯基最近不爱吃饭"))

    system_content = model.received[0][0].content
    assert "柯基" in system_content


@pytest.mark.asyncio
async def test_english_keyword_recall(store: SessionStore, mm: MemoryManager):
    """英文关键词也能正确匹配召回。"""
    await _seed_memory(store, "用户使用 React 框架", "fact")
    agent, model = _recording_agent(store, mm)
    await _collect_events(agent, _ctx(text="帮我优化 React 组件性能"))

    system_content = model.received[0][0].content
    assert "React" in system_content


# ---------------------------------------------------------------------------
# 自动沉淀（6.4，v0.8.1 重开）：挂钩、闸门、每日上限
# ---------------------------------------------------------------------------


class _ExtractRecorder:
    """以正确签名替换 _call_extract：记录调用并返回固定提取结果。"""

    def __init__(self, raw: str) -> None:
        self._raw = raw
        self.calls: list[str] = []

    async def __call__(self, adapter, user_text: str, reply: str) -> str:
        self.calls.append(user_text)
        return self._raw


async def _settle(agent: LLMAgentService) -> None:
    """等待后台提取任务排空（6.4 fire-and-forget 同步点）。"""
    for _ in range(200):
        if not agent._background:
            return
        await asyncio.sleep(0)
    raise AssertionError("后台提取任务未结束")


def _round_agent(store, mm) -> LLMAgentService:
    return LLMAgentService(
        make_test_adapter(ScriptedChatModel(calls=[[AIMessageChunk(content="好")]])),
        store=store,
        memory_manager=mm,
    )


@pytest.mark.asyncio
async def test_auto_extract_stores_memory_after_round(store: SessionStore):
    """完整回合后自动提取落库。"""
    recorder = _ExtractRecorder('[{"category": "fact", "content": "用户养了一只柴犬"}]')
    mm = MemoryManager(store)
    mm._call_extract = recorder
    agent = _round_agent(store, mm)
    await _collect_events(agent, _ctx(text="我家养了一只柴犬哦"))
    await _settle(agent)

    assert recorder.calls == ["我家养了一只柴犬哦"]
    assert any("柴犬" in m["content"] for m in await store.list_memories())


@pytest.mark.asyncio
async def test_auto_extract_disabled_by_config(store: SessionStore):
    """auto_extract=False：不调度提取，仅手动记忆。"""
    recorder = _ExtractRecorder("[]")
    mm = MemoryManager(store, auto_extract=False)
    mm._call_extract = recorder
    agent = _round_agent(store, mm)
    await _collect_events(agent, _ctx(text="记住我喜欢蓝色"))
    await _settle(agent)

    assert recorder.calls == []
    assert await store.list_memories() == []


@pytest.mark.asyncio
async def test_auto_extract_daily_limit(store: SessionStore):
    """今日自动沉淀达到上限后跳过（不发起提取调用）。"""
    for i in range(20):
        await _seed_memory(store, f"自动记忆{i}", source="auto")
    recorder = _ExtractRecorder('[{"category": "fact", "content": "不该入库"}]')
    mm = MemoryManager(store)
    mm._call_extract = recorder
    agent = _round_agent(store, mm)
    await _collect_events(agent, _ctx(text="再多记一条"))
    await _settle(agent)

    assert recorder.calls == []
    assert not any("不该入库" in m["content"] for m in await store.list_memories())


@pytest.mark.asyncio
async def test_daily_limit_counts_only_today_auto(store: SessionStore):
    """每日上限只数今日 auto：今日 manual 不计入。"""
    await _seed_memory(store, "今天的手动记忆", source="manual")
    await _seed_memory(store, "今天的自动记忆", source="auto")
    mm = MemoryManager(store)
    assert await mm._daily_auto_count() == 1
