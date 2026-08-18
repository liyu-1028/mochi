"""ReAct 图（M1-S4，ADR-0008 D3）：自搭 StateGraph 最小循环。

不用 create_react_agent 预构件——状态与流式输出须完全可控以桥接协议事件
（ADR-0008 D3）。拓扑：

    START → agent ──(有 tool_calls)→ tools → agent（回环）
            └─(无 tool_calls)→ END

流式通道（事件桥消费，形态实测 2026-08-18）：
- ``stream_mode="messages"``：LLM chunk 增量（thinking/text/tool_call），
  ToolMessage 亦混入须按类型过滤；节点内手动 ``astream`` 的 chunk 经回调
  捕获（实证）；
- ``stream_mode="custom"``：tools 节点经 ``get_stream_writer`` 实时写出
  工具事件——执行前 ``tool_call_start``、执行后 ``tool_call_end``，时机
  精确（updates 只能事后感知节点完成，不采用）。

工具执行唯一路径：tools 节点经 ToolRegistry.execute（任务 7 危险确认在
该入口前插入）；执行结果无论成败均以 ToolMessage 回灌，模型可自纠。
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .tools.registry import ToolRegistry


def build_react_graph(
    model: BaseChatModel,
    tool_registry: ToolRegistry,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """组装 ReAct 图。无注册工具时不 bind_tools（零行为变更，黄金样例回放）。"""
    tools = tool_registry.langchain_tools()
    bound = model.bind_tools(tools) if tools else model

    async def _agent(state: MessagesState) -> dict:
        merged = None
        async for chunk in bound.astream(state["messages"]):
            # 累加聚合出完整 AIMessage：流末帧不带聚合 tool_calls（ADR-0008 附注）
            merged = chunk if merged is None else merged + chunk
        if merged is None:
            merged = AIMessage(content="")  # 空流：保消息序列完整，路由走 END
        return {"messages": [merged]}

    async def _tools(state: MessagesState) -> dict:
        writer = get_stream_writer()
        outputs: list[ToolMessage] = []
        for call in state["messages"][-1].tool_calls:
            writer(
                {
                    "kind": "tool_call_start",
                    "tool_call_id": call["id"],
                    "name": call["name"],
                    "args": call["args"],
                }
            )
            result = await tool_registry.execute(call["name"], call["args"])
            writer(
                {
                    "kind": "tool_call_end",
                    "tool_call_id": call["id"],
                    "status": "success" if result.ok else "error",
                    "output": result.output,
                }
            )
            # 失败也回灌（内容即可读原因），模型可据此自纠或向用户解释
            outputs.append(ToolMessage(content=result.output, tool_call_id=call["id"]))
        return {"messages": outputs}

    def _route(state: MessagesState) -> str:
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", _agent)
    graph.add_node("tools", _tools)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", _route, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)


def is_llm_chunk(payload: Any) -> bool:
    """messages 模式产出 (chunk, meta)：仅 AIMessageChunk 是 LLM 增量。

    （ToolMessage 等非增量消息也会经该通道流出，事件桥须过滤。）
    """
    chunk = payload[0] if isinstance(payload, tuple) else payload
    return isinstance(chunk, AIMessageChunk)
