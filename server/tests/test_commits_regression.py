"""基于 Git 提交记录的逐 commit 深度测试套件 (Commit-by-Commit Regression Test Suite)。

精准映射提交记录并验证具体功能点与边界：
- c9f7e3c: LangChain 模型 I/O 适配器、端点规整、思考流分拣、异常转译单表、空流守卫
- b9a8c04: 工具注册表双轨原则、五重注册期校验、执行期 Pydantic 校验、异常拦截收敛
- 05f5e07: LangGraph ReAct 图状态机、AIMessageChunk 增量累加、ToolMessage 回灌、Checkpoint Run 级隔离
- 1a2b0fe: tool.confirm 协议数据模型、requiresConfirmation 字段流转、ToolCallStatus 枚举
- 530f7b8: 危险工具确认机制 (interrupt 挂起、allow 恢复、deny 善后回灌、remember 白名单落盘热生效、过期确认容错、取消清理)
- 0fb940c: SessionStore 路径字符串自动包装与懒建目录
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import openai
import pytest
from fakes import ScriptedChatModel, make_test_adapter, sdk_error
from langchain_core.messages import AIMessageChunk, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from mochi_server.agent import (
    DangerLevel,
    LLMAgentService,
    ToolRegistry,
    ToolRegistryError,
    ToolSpec,
)
from mochi_server.agent.adapters.langchain import (
    LangChainAdapter,
    _deltas_from_chunk,
    _ollama_v1_url,
)
from mochi_server.agent.errors import AgentError
from mochi_server.agent.service import AgentContext
from mochi_server.agent.tools.policy import ToolPolicy
from mochi_server.config import ModelProviderConfig
from mochi_server.events import (
    ErrorCode,
    ToolCallStartData,
    ToolConfirmData,
)
from mochi_server.secrets import KeyStore
from mochi_server.store import SessionStore

# ===========================================================================
# 1. 提交 c9f7e3c: 模型 I/O 迁至 langchain 封装
# ===========================================================================


class TestCommit_c9f7e3c_LangChainAdapter:
    def test_ollama_v1_endpoint_formatting(self) -> None:
        """验证 Ollama base_url 自动去除末尾斜杠并补齐 /v1 后缀。"""
        assert _ollama_v1_url(None) == "http://127.0.0.1:11434/v1"
        assert _ollama_v1_url("http://localhost:11434") == "http://localhost:11434/v1"
        assert _ollama_v1_url("http://localhost:11434/") == "http://localhost:11434/v1"
        assert _ollama_v1_url("http://localhost:11434/v1") == "http://localhost:11434/v1"
        assert _ollama_v1_url("http://localhost:11434/v1/") == "http://localhost:11434/v1"

    def test_missing_key_raises_model_auth(self) -> None:
        """验证缺失 API Key 时在构造期立即抛出 MODEL_AUTH 错误。"""
        cfg = ModelProviderConfig(
            kind="openai_compatible",
            display_name="OpenAI",
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
        )
        ks = KeyStore()
        with pytest.raises(AgentError) as exc_info:
            LangChainAdapter("openai", cfg, ks)
        assert exc_info.value.payload.code == ErrorCode.MODEL_AUTH

    def test_sdk_error_translation_matrix(self) -> None:
        """验证 SDK 错误转译单表：401, 403, 404, 429, 402, 500, 超时, 连接断开。"""
        cfg = ModelProviderConfig(
            kind="openai_compatible",
            display_name="OpenAI",
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
        )
        ks = KeyStore()
        ks.set_key("openai", "sk-test")
        adapter = LangChainAdapter("openai", cfg, ks)

        # 401 Unauthorized
        err_401 = adapter.translate_error(sdk_error(openai.AuthenticationError, 401, "Invalid key"))
        assert err_401.payload.code == ErrorCode.MODEL_AUTH
        assert err_401.payload.retryable is False

        # 429 RateLimit
        err_429 = adapter.translate_error(
            sdk_error(openai.RateLimitError, 429, "Too many requests")
        )
        assert err_429.payload.code == ErrorCode.MODEL_RATE_LIMIT
        assert err_429.payload.retryable is True

        # 402 Payment Required
        err_402 = adapter.translate_error(
            sdk_error(openai.APIStatusError, 402, "Insufficient balance")
        )
        assert err_402.payload.code == ErrorCode.MODEL_QUOTA
        assert err_402.payload.retryable is False

        # 500 Server Error
        err_500 = adapter.translate_error(
            sdk_error(openai.InternalServerError, 500, "Server error")
        )
        assert err_500.payload.code == ErrorCode.MODEL_UNAVAILABLE
        assert err_500.payload.retryable is True

        # Timeout
        err_timeout = adapter.translate_error(sdk_error(openai.APITimeoutError, 0, "Timeout"))
        assert err_timeout.payload.code == ErrorCode.NETWORK
        assert err_timeout.payload.retryable is True

    def test_thinking_stream_extraction(self) -> None:
        """验证 content block 中的 thinking 块与 text 块正确分拣。"""
        chunk = AIMessageChunk(
            content=[
                {"type": "thinking", "thinking": "深度推理中..."},
                {"type": "text", "text": "最终答复"},
            ]
        )
        deltas = list(_deltas_from_chunk(chunk))
        assert deltas == [("thinking", "深度推理中..."), ("text", "最终答复")]

    @pytest.mark.asyncio
    async def test_empty_stream_triggers_guard(self) -> None:
        """验证流结束未返回任何 token 时触发空流守卫。"""
        model = ScriptedChatModel(calls=[[AIMessageChunk(content="")]])
        adapter = make_test_adapter(model)
        with pytest.raises(AgentError) as exc_info:
            async for _ in adapter.stream_chat([], run_id="r-empty"):
                pass
        assert exc_info.value.payload.code == ErrorCode.MODEL_UNAVAILABLE
        assert "没有返回任何内容" in exc_info.value.payload.message


# ===========================================================================
# 2. 提交 b9a8c04: 工具注册表——声明/执行双轨与危险分级
# ===========================================================================


class DummyToolArgs(BaseModel):
    query: str = Field(description="搜索关键词")
    count: int = Field(default=5, description="数量")


async def _dummy_executor(args: dict[str, Any]) -> str:
    return f"search_results_{args['query']}_{args['count']}"


class TestCommit_b9a8c04_ToolRegistry:
    def test_five_registration_validations(self) -> None:
        """验证注册期五重校验：命名正则、重复名、描述非空、BaseModel Schema、异步执行器。"""
        reg = ToolRegistry()

        # 1. 命名非法
        with pytest.raises(ToolRegistryError, match="不合规"):
            reg.register(
                ToolSpec(
                    name="Tool_Bad",
                    description="d",
                    args_schema=DummyToolArgs,
                    executor=_dummy_executor,
                )
            )

        # 2. 描述非法
        with pytest.raises(ToolRegistryError, match="description"):
            reg.register(
                ToolSpec(
                    name="tool_ok",
                    description="  ",
                    args_schema=DummyToolArgs,
                    executor=_dummy_executor,
                )
            )

        # 3. Schema 非 BaseModel
        with pytest.raises(ToolRegistryError, match="BaseModel"):
            reg.register(
                ToolSpec(
                    name="tool_ok", description="d", args_schema=dict, executor=_dummy_executor
                )
            )  # type: ignore[arg-type]

        # 4. 同步函数
        def _sync_fn(args):
            return "sync"

        with pytest.raises(ToolRegistryError, match="async 函数"):
            reg.register(
                ToolSpec(
                    name="tool_ok", description="d", args_schema=DummyToolArgs, executor=_sync_fn
                )
            )  # type: ignore[arg-type]

        # 5. 成功注册及重复注册拦截
        reg.register(
            ToolSpec(
                name="tool_ok", description="d", args_schema=DummyToolArgs, executor=_dummy_executor
            )
        )
        with pytest.raises(ToolRegistryError, match="重复注册"):
            reg.register(
                ToolSpec(
                    name="tool_ok",
                    description="d",
                    args_schema=DummyToolArgs,
                    executor=_dummy_executor,
                )
            )

    def test_two_track_principle(self) -> None:
        """验证双轨原则：声明轨生成 StructuredTool，执行轨统一收口 execute。"""
        reg = ToolRegistry()
        reg.register(
            ToolSpec(
                name="search_items",
                description="搜索项目",
                args_schema=DummyToolArgs,
                executor=_dummy_executor,
                danger=DangerLevel.DANGEROUS,
            )
        )

        # 声明轨
        lc_tools = reg.langchain_tools()
        assert len(lc_tools) == 1
        assert lc_tools[0].name == "search_items"
        assert lc_tools[0].description == "搜索项目"

        # 危险分级保持
        spec = reg.get("search_items")
        assert spec is not None
        assert spec.danger == DangerLevel.DANGEROUS

    @pytest.mark.asyncio
    async def test_execute_error_code_classification(self) -> None:
        """验证执行轨异常分类收敛：unknown_tool / invalid_args / execution_error。"""
        reg = ToolRegistry()
        reg.register(
            ToolSpec(
                name="test_tool",
                description="d",
                args_schema=DummyToolArgs,
                executor=_dummy_executor,
            )
        )

        # 1. unknown_tool
        r1 = await reg.execute("no_such_tool", {})
        assert r1.ok is False
        assert r1.error_code == "unknown_tool"

        # 2. invalid_args
        r2 = await reg.execute("test_tool", {})  # 缺少必填 query
        assert r2.ok is False
        assert r2.error_code == "invalid_args"

        # 3. execution_error
        async def _boom(args):
            raise RuntimeError("disk failure")

        reg_boom = ToolRegistry()
        reg_boom.register(
            ToolSpec(name="boom_tool", description="d", args_schema=DummyToolArgs, executor=_boom)
        )
        r3 = await reg_boom.execute("boom_tool", {"query": "test"})
        assert r3.ok is False
        assert r3.error_code == "execution_error"


# ===========================================================================
# 3. 提交 05f5e07: LangGraph 图内核——ReAct 回环与事件桥
# ===========================================================================


def _tool_call_chunk(name: str, args: dict[str, Any], call_id: str = "tc-1") -> AIMessageChunk:
    import json

    return AIMessageChunk(
        content="",
        tool_call_chunks=[
            {
                "name": name,
                "args": json.dumps(args),
                "id": call_id,
                "index": 0,
                "type": "tool_call_chunk",
            }
        ],
    )


class TestCommit_05f5e07_LangGraphKernel:
    @pytest.mark.asyncio
    async def test_react_loop_and_tool_message_feedback(self) -> None:
        """验证 ReAct 状态图：模型发出 tool_call -> 执行工具 -> ToolMessage 回灌 -> 模型输出文本。"""
        reg = ToolRegistry()
        reg.register(
            ToolSpec(
                name="query_db",
                description="查询",
                args_schema=DummyToolArgs,
                executor=_dummy_executor,
            )
        )

        calls = [
            [_tool_call_chunk("query_db", {"query": "mochi", "count": 3})],
            [AIMessageChunk(content="查询完毕，找到 3 条记录")],
        ]
        model = ScriptedChatModel(calls=calls)
        agent = LLMAgentService(make_test_adapter(model), tool_registry=reg)

        ctx = AgentContext(run_id="r-react", session_id="s-react", text="查数据")
        events = [(t, p) async for t, p in agent.run(ctx)]
        types = [t for t, _ in events]

        # 事件时序
        assert types == [
            "state.change",  # thinking
            "thinking.start",
            "thinking.end",
            "state.change",  # working
            "tool.call.start",
            "tool.call.end",
            "state.change",  # talking
            "emotion",
            "text.start",
            "text.delta",
            "text.end",
            "state.change",  # idle
        ]

        # 验证模型第二轮收到 ToolMessage 回灌
        assert len(model.received) == 2
        second_input = model.received[1]
        tool_msg = next(m for m in second_input if isinstance(m, ToolMessage))
        assert tool_msg.tool_call_id == "tc-1"
        assert tool_msg.content == "search_results_mochi_3"


# ===========================================================================
# 4. 提交 1a2b0fe: 协议 tool.confirm 与 requiresConfirmation
# ===========================================================================


class TestCommit_1a2b0fe_ProtocolConfirm:
    def test_tool_confirm_data_serialization(self) -> None:
        """验证 ToolConfirmData 的 camelCase 别名与必填/默认字段。"""
        raw = {"runId": "r-1", "toolCallId": "tc-1", "decision": "allow", "remember": True}
        data = ToolConfirmData.model_validate(raw)
        assert data.run_id == "r-1"
        assert data.tool_call_id == "tc-1"
        assert data.decision == "allow"
        assert data.remember is True

        # remember 默认为 False
        data_default = ToolConfirmData.model_validate(
            {"runId": "r-1", "toolCallId": "tc-1", "decision": "deny"}
        )
        assert data_default.remember is False

    def test_tool_call_start_requires_confirmation_field(self) -> None:
        """验证 ToolCallStartData 的 requires_confirmation 字段。"""
        d1 = ToolCallStartData(run_id="r-1", tool_call_id="tc-1", name="fs.write", args={})
        assert d1.requires_confirmation is False

        d2 = ToolCallStartData(
            run_id="r-1", tool_call_id="tc-1", name="fs.write", args={}, requires_confirmation=True
        )
        assert d2.requires_confirmation is True


# ===========================================================================
# 5. 提交 530f7b8: 危险工具确认机制 (interrupt / allow / deny / remember)
# ===========================================================================


class TestCommit_530f7b8_DangerousConfirmMechanism:
    @staticmethod
    def _make_policy() -> tuple[ToolPolicy, list[str]]:
        whitelist: list[str] = []

        def _save(names: list[str]) -> None:
            whitelist[:] = list(names)

        return ToolPolicy(load=lambda: list(whitelist), save=_save), whitelist

    @staticmethod
    async def _wait_pending(agent: LLMAgentService, run_id: str) -> None:
        for _ in range(500):
            if agent.has_pending(run_id):
                return
            await asyncio.sleep(0)
        raise AssertionError(f"等待挂起超时：run={run_id}")

    @staticmethod
    async def _collect(agent: LLMAgentService, ctx: AgentContext) -> list[tuple[str, Any]]:
        return [(t, p) async for t, p in agent.run(ctx)]

    @pytest.mark.asyncio
    async def test_dangerous_tool_triggers_interrupt_and_allow_flow(self) -> None:
        """验证危险工具触发 requiresConfirmation: true，挂起等待，allow 确认后继续执行。"""
        reg = ToolRegistry()
        reg.register(
            ToolSpec(
                name="delete_files",
                description="删除文件",
                args_schema=DummyToolArgs,
                executor=_dummy_executor,
                danger=DangerLevel.DANGEROUS,
            )
        )

        policy, _ = self._make_policy()
        saver = InMemorySaver()

        calls = [
            [_tool_call_chunk("delete_files", {"query": "temp", "count": 1})],
            [AIMessageChunk(content="文件已成功删除")],
        ]
        model = ScriptedChatModel(calls=calls)
        agent = LLMAgentService(
            make_test_adapter(model),
            tool_registry=reg,
            checkpointer=saver,
            tool_policy=policy,
        )

        ctx = AgentContext(run_id="r-confirm-allow", session_id="s-confirm", text="删文件")
        task = asyncio.create_task(self._collect(agent, ctx))
        await self._wait_pending(agent, "r-confirm-allow")

        assert agent.has_pending("r-confirm-allow") is True
        confirmed = await agent.confirm("r-confirm-allow", "tc-1", "allow", remember=False)
        assert confirmed is True

        events = await task

        start_evt = next(p for t, p in events if t == "tool.call.start")
        assert start_evt.requires_confirmation is True
        assert start_evt.name == "delete_files"

        end_evt = next(p for t, p in events if t == "tool.call.end")
        assert end_evt.status == "success"

        text_end = next(p for t, p in events if t == "text.end")
        assert text_end.full_text == "文件已成功删除"

    @pytest.mark.asyncio
    async def test_dangerous_tool_deny_flow_injects_remediation(self) -> None:
        """验证危险工具用户 deny 拒绝：tool.call.end(status='denied')，善后 ToolMessage 回灌模型。"""
        reg = ToolRegistry()
        reg.register(
            ToolSpec(
                name="delete_files",
                description="删除文件",
                args_schema=DummyToolArgs,
                executor=_dummy_executor,
                danger=DangerLevel.DANGEROUS,
            )
        )

        policy, _ = self._make_policy()
        saver = InMemorySaver()

        calls = [
            [_tool_call_chunk("delete_files", {"query": "temp", "count": 1})],
            [AIMessageChunk(content="收到，已取消删除操作。")],
        ]
        model = ScriptedChatModel(calls=calls)
        agent = LLMAgentService(
            make_test_adapter(model),
            tool_registry=reg,
            checkpointer=saver,
            tool_policy=policy,
        )

        ctx = AgentContext(run_id="r-confirm-deny", session_id="s-confirm", text="删文件")
        task = asyncio.create_task(self._collect(agent, ctx))
        await self._wait_pending(agent, "r-confirm-deny")

        confirmed = await agent.confirm("r-confirm-deny", "tc-1", "deny", remember=False)
        assert confirmed is True

        events = await task

        end_evt = next(p for t, p in events if t == "tool.call.end")
        assert end_evt.status == "denied"

        second_msgs = model.received[1]
        tool_msg = next(m for m in second_msgs if isinstance(m, ToolMessage))
        assert "用户拒绝了这次操作" in tool_msg.content

    @pytest.mark.asyncio
    async def test_remember_allow_persists_and_skips_next_time(self) -> None:
        """验证 remember=True 写入白名单，同一工具下次调用免弹窗确认。"""
        reg = ToolRegistry()
        reg.register(
            ToolSpec(
                name="write_file",
                description="写入文件",
                args_schema=DummyToolArgs,
                executor=_dummy_executor,
                danger=DangerLevel.DANGEROUS,
            )
        )

        policy, whitelist = self._make_policy()
        saver = InMemorySaver()

        # 第 1 轮：弹窗并勾选 remember
        calls_1 = [
            [_tool_call_chunk("write_file", {"query": "a", "count": 1})],
            [AIMessageChunk(content="写入完成 1")],
        ]
        model_1 = ScriptedChatModel(calls=calls_1)
        agent_1 = LLMAgentService(
            make_test_adapter(model_1), tool_registry=reg, checkpointer=saver, tool_policy=policy
        )

        ctx_1 = AgentContext(run_id="r-rem-1", session_id="s-rem", text="写文件 1")
        task_1 = asyncio.create_task(self._collect(agent_1, ctx_1))
        await self._wait_pending(agent_1, "r-rem-1")

        await agent_1.confirm("r-rem-1", "tc-1", "allow", remember=True)
        await task_1

        assert policy.is_allowed("write_file") is True
        assert "write_file" in whitelist

        # 第 2 轮：同工具再次调用，应直接执行，不再挂起
        calls_2 = [
            [_tool_call_chunk("write_file", {"query": "b", "count": 2})],
            [AIMessageChunk(content="写入完成 2")],
        ]
        model_2 = ScriptedChatModel(calls=calls_2)
        agent_2 = LLMAgentService(
            make_test_adapter(model_2), tool_registry=reg, checkpointer=saver, tool_policy=policy
        )

        ctx_2 = AgentContext(run_id="r-rem-2", session_id="s-rem", text="写文件 2")
        events_2 = [(t, p) async for t, p in agent_2.run(ctx_2)]

        start_evt = next(p for t, p in events_2 if t == "tool.call.start")
        assert start_evt.requires_confirmation is False
        assert agent_2.has_pending("r-rem-2") is False

    @pytest.mark.asyncio
    async def test_stale_or_mismatched_confirm_returns_false(self) -> None:
        """验证过期或不匹配的 tool.confirm 返回 False，不造成异常崩溃。"""
        agent = LLMAgentService(make_test_adapter(ScriptedChatModel(calls=[])))
        res1 = await agent.confirm("r-non-existent", "tc-1", "allow")
        assert res1 is False

    @pytest.mark.asyncio
    async def test_cancel_during_pending_cleans_table(self) -> None:
        """验证挂起等待期间如果被 cancel 取消，挂起表被清理。"""
        reg = ToolRegistry()
        reg.register(
            ToolSpec(
                name="dangerous_tool",
                description="d",
                args_schema=DummyToolArgs,
                executor=_dummy_executor,
                danger=DangerLevel.DANGEROUS,
            )
        )
        policy = ToolPolicy(load=lambda: [], save=lambda _items: None)
        saver = InMemorySaver()

        model = ScriptedChatModel(
            calls=[[_tool_call_chunk("dangerous_tool", {"query": "x", "count": 1})]]
        )
        agent = LLMAgentService(
            make_test_adapter(model), tool_registry=reg, checkpointer=saver, tool_policy=policy
        )

        ctx = AgentContext(run_id="r-cancel", session_id="s-cancel", text="操作")

        task = asyncio.create_task(self._collect(agent, ctx))
        await self._wait_pending(agent, "r-cancel")

        assert agent.has_pending("r-cancel") is True

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert agent.has_pending("r-cancel") is False


# ===========================================================================
# 6. 提交 0fb940c: SessionStore 自定义 db_path 补 Path 包装
# ===========================================================================


class TestCommit_0fb940c_SessionStorePath:
    @pytest.mark.asyncio
    async def test_session_store_str_path_resolution(self, tmp_path: Path) -> None:
        """验证 SessionStore 传入 str 类型路径时正常解析并创建父目录与库文件。"""
        str_path = str(tmp_path / "sub_dir" / "custom.db")
        store = SessionStore(str_path)

        await store.append_message("sess-1", "user", "你好")
        msgs = await store.get_messages("sess-1")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "你好"

        await store.close()
        assert Path(str_path).exists() is True
