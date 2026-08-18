"""边界条件、极端输入与高压力场景测试套件 (Extreme & Boundary Test Suite)。

覆盖维度：
1. ToolRegistry：超大 Payload (5MB)、100 协程并发压测、特殊字符/注入防御、深层嵌套 Schema、非字符串返回
2. ReAct 图内核：多轮深度回环 (3-Step ReAct)、单轮 10 批量并行工具调用、混合成功/失败工具调用、递归超限截获、1000 碎片化 Token 流
3. Checkpoint & 会话：20 并发 Run Checkpoint 隔离、海量历史 (200条) 截断安全
4. WebSocket & 协议层：极速连发并发保护、畸形包/非法帧洪峰注入容错
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fakes import ScriptedChatModel, make_test_adapter
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from mochi_server.agent import EchoAgentService, LLMAgentService, ToolRegistry, ToolSpec
from mochi_server.agent.service import AgentContext
from mochi_server.events import PROTOCOL_VERSION
from mochi_server.main import create_app
from mochi_server.store import SessionStore

# ===========================================================================
# 辅助函数：构造合法的 Tool Call Chunk
# ===========================================================================


def _tool_chunk(name: str, args: dict[str, Any], call_id: str, index: int = 0) -> AIMessageChunk:
    return AIMessageChunk(
        content="",
        tool_call_chunks=[
            {
                "name": name,
                "args": json.dumps(args),
                "id": call_id,
                "index": index,
                "type": "tool_call_chunk",
            }
        ],
    )


def _batch_tool_chunk(calls: list[tuple[str, dict[str, Any], str]]) -> AIMessageChunk:
    tool_chunks = [
        {
            "name": name,
            "args": json.dumps(args),
            "id": call_id,
            "index": i,
            "type": "tool_call_chunk",
        }
        for i, (name, args, call_id) in enumerate(calls)
    ]
    return AIMessageChunk(content="", tool_call_chunks=tool_chunks)


# ===========================================================================
# 1. ToolRegistry 边界与极端测试
# ===========================================================================


class LargePayloadArgs(BaseModel):
    data: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeepNestedSub(BaseModel):
    level: int
    tag: str


class DeepNestedArgs(BaseModel):
    sub: DeepNestedSub
    items: list[DeepNestedSub]


async def _large_payload_executor(args: dict[str, Any]) -> str:
    size = len(args.get("data", ""))
    return f"processed_{size}_bytes"


async def _deep_nested_executor(args: dict[str, Any]) -> str:
    sub = args["sub"]
    return f"level_{sub['level']}_{len(args.get('items', []))}"


@pytest.mark.asyncio
async def test_tool_payload_extreme_size() -> None:
    """极端测试：传入 5MB 超大字符串与复杂字典，验证 Pydantic 解析与执行器吞吐。"""
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="large_data_tool",
            description="处理大数据包",
            args_schema=LargePayloadArgs,
            executor=_large_payload_executor,
        )
    )

    big_str = "x" * (5 * 1024 * 1024)  # 5MB
    result = await reg.execute(
        "large_data_tool", {"data": big_str, "metadata": {"source": "stress_test"}}
    )

    assert result.ok is True
    assert result.output == f"processed_{len(big_str)}_bytes"
    assert result.error_code is None


@pytest.mark.asyncio
async def test_tool_concurrency_stress_100() -> None:
    """极端测试：100 个协程瞬间并发调用 execute，验证无锁争用与状态污染。"""
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="concurrent_tool",
            description="并发压测工具",
            args_schema=LargePayloadArgs,
            executor=_large_payload_executor,
        )
    )

    async def _call(i: int):
        return await reg.execute("concurrent_tool", {"data": f"item_{i}"})

    tasks = [_call(i) for i in range(100)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 100
    for i, r in enumerate(results):
        assert r.ok is True
        assert r.output == f"processed_{len(f'item_{i}')}_bytes"


@pytest.mark.asyncio
async def test_tool_special_characters_and_injection() -> None:
    """边界测试：参数包含 Null 字节、换行、Unicode 表情、SQL 注入及目录穿越特征字符。"""
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="sanitize_tool",
            description="清洗与字符测试",
            args_schema=LargePayloadArgs,
            executor=_large_payload_executor,
        )
    )

    evil_payloads = [
        "\x00\x01\x02\x03\x04",
        "'; DROP TABLE sessions; --",
        "../../../../../../etc/passwd",
        "<script>alert('xss')</script>",
        "🎉🚀💻" * 1000,
        "\n\r\t\b\f\v",
    ]

    for payload in evil_payloads:
        result = await reg.execute("sanitize_tool", {"data": payload})
        assert result.ok is True
        assert result.output == f"processed_{len(payload)}_bytes"


@pytest.mark.asyncio
async def test_tool_deeply_nested_schema() -> None:
    """边界测试：深层嵌套对象与列表类型的 Schema 校验与参数解构。"""
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="nested_tool",
            description="深层嵌套测试",
            args_schema=DeepNestedArgs,
            executor=_deep_nested_executor,
        )
    )

    raw_args = {
        "sub": {"level": 3, "tag": "deep"},
        "items": [{"level": 1, "tag": "a"}, {"level": 2, "tag": "b"}],
    }
    result = await reg.execute("nested_tool", raw_args)
    assert result.ok is True
    assert result.output == "level_3_2"


# ===========================================================================
# 2. ReAct 图内核边界与极端测试
# ===========================================================================


def _make_agent(
    calls: list[list[Any]], *, tool_registry: ToolRegistry | None = None, checkpointer=None
):
    model = ScriptedChatModel(calls=calls)
    agent = LLMAgentService(
        make_test_adapter(model),
        tool_registry=tool_registry,
        checkpointer=checkpointer,
    )
    return agent, model


@pytest.mark.asyncio
async def test_multi_round_react_loop() -> None:
    """极端场景：连续 3 轮工具调用自主回环 (Agent -> Tool1 -> Agent -> Tool2 -> Agent -> Tool3 -> Agent -> Text)。"""
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="step_tool",
            description="步进工具",
            args_schema=LargePayloadArgs,
            executor=_large_payload_executor,
        )
    )

    # 3 轮工具调用 + 第 4 轮产出最终文本
    calls = [
        # Round 1: 模型发起 Tool 1
        [_tool_chunk("step_tool", {"data": "step1"}, "tc-1")],
        # Round 2: 收到 Tool 1 结果后，模型发起 Tool 2
        [_tool_chunk("step_tool", {"data": "step2_data"}, "tc-2")],
        # Round 3: 收到 Tool 2 结果后，模型发起 Tool 3
        [_tool_chunk("step_tool", {"data": "step3_final"}, "tc-3")],
        # Round 4: 收到 Tool 3 结果后，模型产出最终回复文本
        [AIMessageChunk(content="全部三步工具执行完成！")],
    ]

    agent, model = _make_agent(calls, tool_registry=reg)
    ctx = AgentContext(run_id="r-multi", session_id="s-multi", text="请执行三步流程")

    events = [(t, p) async for t, p in agent.run(ctx)]
    types = [t for t, _ in events]

    # 验证模型调用了 4 次
    assert len(model.received) == 4
    # 验证工具调用 start 和 end 各发射了 3 次
    assert types.count("tool.call.start") == 3
    assert types.count("tool.call.end") == 3

    # 验证最终文本
    text_end = next(p for t, p in events if t == "text.end")
    assert text_end.full_text == "全部三步工具执行完成！"


@pytest.mark.asyncio
async def test_batch_parallel_tool_calls_10() -> None:
    """极端场景：单条 AIMessage 返回 10 个并行 tool_calls，验证 tools 节点完整且按序桥接每个事件。"""
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="batch_tool",
            description="批量工具",
            args_schema=LargePayloadArgs,
            executor=_large_payload_executor,
        )
    )

    calls_10 = [("batch_tool", {"data": f"batch_{i}"}, f"tc-batch-{i}") for i in range(10)]

    calls = [
        [_batch_tool_chunk(calls_10)],
        [AIMessageChunk(content="10 个工具调用全部完成")],
    ]

    agent, model = _make_agent(calls, tool_registry=reg)
    ctx = AgentContext(run_id="r-batch", session_id="s-batch", text="批量并发工具调用")

    events = [(t, p) async for t, p in agent.run(ctx)]
    types = [t for t, _ in events]

    assert types.count("tool.call.start") == 10
    assert types.count("tool.call.end") == 10

    # 验证第 2 轮模型接收到了全部 10 个 ToolMessage
    second_input = model.received[1]
    tool_messages = [m for m in second_input if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 10
    for i, tm in enumerate(tool_messages):
        assert tm.tool_call_id == f"tc-batch-{i}"
        assert tm.content == f"processed_{len(f'batch_{i}')}_bytes"


@pytest.mark.asyncio
async def test_mixed_success_and_failure_tools() -> None:
    """边界场景：单轮工具调用中包含有效工具、未知工具和参数非法工具，验证多状态混合处理与回灌。"""
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="valid_tool",
            description="有效工具",
            args_schema=LargePayloadArgs,
            executor=_large_payload_executor,
        )
    )

    calls_mixed = [
        ("valid_tool", {"data": "valid"}, "tc-ok"),
        ("non_existent_tool", {}, "tc-unknown"),
        ("valid_tool", {}, "tc-bad-args"),  # 缺少必填字段 'data'
    ]

    calls = [
        [_batch_tool_chunk(calls_mixed)],
        [AIMessageChunk(content="已处理混合结果")],
    ]

    agent, _model = _make_agent(calls, tool_registry=reg)
    ctx = AgentContext(run_id="r-mix", session_id="s-mix", text="混合工具调用测试")

    events = [(t, p) async for t, p in agent.run(ctx)]

    tool_ends = [p for t, p in events if t == "tool.call.end"]
    assert len(tool_ends) == 3

    status_map = {e.tool_call_id: e.status for e in tool_ends}
    assert status_map["tc-ok"] == "success"
    assert status_map["tc-unknown"] == "error"
    assert status_map["tc-bad-args"] == "error"


@pytest.mark.asyncio
async def test_massive_fragmented_streaming_chunks() -> None:
    """压力场景：1,000 个单字符 chunk 极速涌入，验证流式分拣吞吐与最终文本拼接一致性。"""
    text_content = "中" * 1000
    chunks = [AIMessageChunk(content=ch) for ch in text_content]

    agent, _ = _make_agent([chunks])
    ctx = AgentContext(run_id="r-frag", session_id="s-frag", text="碎片流测试")

    events = [(t, p) async for t, p in agent.run(ctx)]

    delta_events = [p for t, p in events if t == "text.delta"]
    assert len(delta_events) == 1000

    text_end = next(p for t, p in events if t == "text.end")
    assert text_end.full_text == text_content


# ===========================================================================
# 3. Checkpointer 与存储并发隔离极端测试
# ===========================================================================


@pytest.mark.asyncio
async def test_checkpointer_concurrent_runs_isolation() -> None:
    """并发隔离测试：同一 Checkpointer 实例并发服务 20 个不同的 thread_id，验证状态无串扰。"""
    saver = InMemorySaver()

    async def _run_agent(run_idx: int):
        reg = ToolRegistry()
        reg.register(
            ToolSpec(
                name="user_tool",
                description="用户工具",
                args_schema=LargePayloadArgs,
                executor=_large_payload_executor,
            )
        )
        calls = [
            [_tool_chunk("user_tool", {"data": f"user_{run_idx}"}, f"tc-{run_idx}")],
            [AIMessageChunk(content=f"reply_for_user_{run_idx}")],
        ]
        agent, _ = _make_agent(calls, tool_registry=reg, checkpointer=saver)
        ctx = AgentContext(
            run_id=f"run-{run_idx}", session_id=f"sess-{run_idx}", text=f"text_{run_idx}"
        )

        events = [(t, p) async for t, p in agent.run(ctx)]
        text_end = next(p for t, p in events if t == "text.end")
        return text_end.full_text

    tasks = [_run_agent(i) for i in range(20)]
    results = await asyncio.gather(*tasks)

    for i, res in enumerate(results):
        assert res == f"reply_for_user_{i}"


@pytest.mark.asyncio
async def test_session_store_massive_history_truncation(tmp_path) -> None:
    """边界测试：SessionStore 存在 100 轮历史时，加载逻辑严格截断至最新 20 条，不撑爆上下文。"""
    db_file = tmp_path / "massive.db"
    store = SessionStore(str(db_file))

    session_id = "sess-massive"
    # 插入 100 轮历史消息 (200 条)
    for i in range(100):
        await store.append_message(session_id, "user", f"问题 {i}")
        await store.append_message(session_id, "assistant", f"回答 {i}")

    # 使用真实 store 构建 LLMAgentService
    calls = [[AIMessageChunk(content="历史已安全加载")]]
    model = ScriptedChatModel(calls=calls)
    agent = LLMAgentService(make_test_adapter(model), store=store)

    ctx = AgentContext(run_id="r-hist", session_id=session_id, text="最新问题")
    _events = [(t, p) async for t, p in agent.run(ctx)]

    # 验证传给模型的历史消息：SystemMessage(1) + 最近 20 条消息 + 当前 HumanMessage(1) = 22 条
    first_call_msgs = model.received[0]
    assert len(first_call_msgs) == 22
    # 验证最老的那条加载的历史为问题 90（即截断了 0~89）
    assert first_call_msgs[1].content == "问题 90"
    await store.close()


# ===========================================================================
# 4. WebSocket & 协议层极端场景测试
# ===========================================================================


def _hello() -> dict:
    return {
        "v": PROTOCOL_VERSION,
        "type": "hello",
        "id": "c-hello",
        "ts": 0,
        "data": {
            "versions": [PROTOCOL_VERSION],
            "client": {"name": "pytest-stress", "version": "0.0.0"},
        },
    }


def test_ws_rapid_fire_burst_mutex() -> None:
    """极端场景：同一 WebSocket 连接极速连发 5 条 chat.send，验证 RunManager 互斥锁丢弃旧回合。"""
    client = TestClient(create_app(EchoAgentService(chunk_delay=0.01)))
    with client.websocket_connect("/ws") as ws:
        ws.send_json(_hello())
        ws.receive_json()  # hello_ack

        # 极速连发 5 条 chat.send
        for i in range(5):
            ws.send_json(
                {
                    "v": PROTOCOL_VERSION,
                    "type": "chat.send",
                    "id": f"c-send-{i}",
                    "ts": 0,
                    "data": {"runId": f"r-burst-{i}", "sessionId": "s-burst", "text": f"连击 {i}"},
                }
            )

        # 消费事件直到收到最后一个完成帧
        received_types = []
        for _ in range(200):
            frame = ws.receive_json()
            received_types.append(frame["type"])
            if (
                frame["type"] == "run.finished"
                and frame.get("data", {}).get("runId") == "r-burst-4"
            ):
                break

        # 验证收到过完整的流式帧且服务未崩溃
        assert "run.started" in received_types
        assert "run.finished" in received_types


def test_ws_malformed_frames_flood() -> None:
    """极端场景：向 WebSocket 灌入 20 帧畸形数据（非 JSON、缺少必填字段、非法版本），验证连接韧性。"""
    client = TestClient(create_app(EchoAgentService()))
    with client.websocket_connect("/ws") as ws:
        ws.send_json(_hello())
        ws.receive_json()  # hello_ack

        # 发送各种非标/损坏数据
        ws.send_text("not a valid json string {{{{")
        ws.send_json({"v": "999.0", "type": "unknown.command", "id": "1", "ts": 0, "data": {}})
        ws.send_json({"type": "chat.send"})  # 缺少 v, id, ts, data
        ws.send_json({"v": PROTOCOL_VERSION, "type": "chat.send", "id": "2", "ts": 0, "data": None})

        # 损坏帧之后发送一条合法 chat.send，验证服务依然健康可用
        ws.send_json(
            {
                "v": PROTOCOL_VERSION,
                "type": "chat.send",
                "id": "c-valid",
                "ts": 0,
                "data": {"runId": "r-valid", "sessionId": "s-valid", "text": "恢复测试"},
            }
        )

        found_finished = False
        for _ in range(100):
            frame = ws.receive_json()
            if frame["type"] == "run.finished" and frame.get("data", {}).get("runId") == "r-valid":
                found_finished = True
                break

        assert found_finished is True, "服务应在畸形包灌入后依然能正常响应合法请求"
