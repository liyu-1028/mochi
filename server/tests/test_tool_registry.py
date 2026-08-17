"""工具注册表测试（M1-S4，ADR-0008 D5）：注册校验、声明轨桥接、执行轨收敛。"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field

from mochi_server.agent import DangerLevel, ToolRegistry, ToolRegistryError, ToolSpec


class EchoArgs(BaseModel):
    text: str = Field(description="要回显的文本")
    times: int = Field(default=1, ge=1, le=5, description="重复次数")


async def _echo_executor(args: dict[str, Any]) -> str:
    return args["text"] * args["times"]


def _spec(**overrides) -> ToolSpec:
    params: dict[str, Any] = {
        "name": "echo_text",
        "description": "回显文本的示例工具",
        "args_schema": EchoArgs,
        "executor": _echo_executor,
    }
    params.update(overrides)
    return ToolSpec(**params)


# ---------------------------------------------------------------------------
# 注册与查询
# ---------------------------------------------------------------------------


def test_register_and_roundtrip() -> None:
    registry = ToolRegistry()
    registry.register(_spec())
    spec = registry.get("echo_text")
    assert spec is not None
    assert spec.description == "回显文本的示例工具"
    assert spec.danger is DangerLevel.SAFE  # 默认分级
    assert [s.name for s in registry.list_specs()] == ["echo_text"]


def test_dangerous_level_preserved() -> None:
    registry = ToolRegistry()
    registry.register(_spec(danger=DangerLevel.DANGEROUS))
    assert registry.get("echo_text").danger is DangerLevel.DANGEROUS


def test_get_unknown_returns_none() -> None:
    assert ToolRegistry().get("ghost") is None


# ---------------------------------------------------------------------------
# 注册校验（五连）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_name", ["Echo", "echo-text", "回显", "1echo", "a" * 65, ""])
def test_register_rejects_invalid_name(bad_name: str) -> None:
    with pytest.raises(ToolRegistryError, match="不合规"):
        ToolRegistry().register(_spec(name=bad_name))


def test_register_rejects_duplicate_name() -> None:
    registry = ToolRegistry()
    registry.register(_spec())
    with pytest.raises(ToolRegistryError, match="重复"):
        registry.register(_spec(description="另一个描述"))


@pytest.mark.parametrize("bad_desc", ["", " ", "x" * 1025])
def test_register_rejects_bad_description(bad_desc: str) -> None:
    with pytest.raises(ToolRegistryError, match="description"):
        ToolRegistry().register(_spec(description=bad_desc))


def test_register_rejects_non_pydantic_schema() -> None:
    with pytest.raises(ToolRegistryError, match="BaseModel"):
        ToolRegistry().register(_spec(args_schema=dict[str, str]))  # type: ignore[arg-type]


def test_register_rejects_sync_executor() -> None:
    with pytest.raises(ToolRegistryError, match="async"):

        def _sync_executor(args: dict[str, Any]) -> str:  # pragma: no cover
            return args["text"]

        ToolRegistry().register(_spec(executor=_sync_executor))


# ---------------------------------------------------------------------------
# 声明轨：langchain_tools 桥接
# ---------------------------------------------------------------------------


def test_langchain_tools_carries_declaration() -> None:
    registry = ToolRegistry()
    registry.register(_spec())
    tools = registry.langchain_tools()
    assert len(tools) == 1
    assert tools[0].name == "echo_text"
    assert tools[0].description == "回显文本的示例工具"
    # JSON schema 与 args_schema 字段一致（含字段级 description）
    args = tools[0].args
    assert args["text"]["type"] == "string"
    assert args["text"]["description"] == "要回显的文本"
    assert args["times"]["default"] == 1


@pytest.mark.asyncio
async def test_langchain_tool_ainvoke_routes_to_execute() -> None:
    """LC coroutine 以 kwargs 展开传参（实测 2026-08-18）→ 桥接适配回 dict。"""
    registry = ToolRegistry()
    registry.register(_spec())
    tool = registry.langchain_tools()[0]
    result = await tool.ainvoke({"text": "嗨", "times": 2})
    assert result.ok is True
    assert result.output == "嗨嗨"


# ---------------------------------------------------------------------------
# 执行轨：execute 四路
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_success() -> None:
    registry = ToolRegistry()
    registry.register(_spec())
    result = await registry.execute("echo_text", {"text": "好", "times": 3})
    assert result.ok is True
    assert result.output == "好好好"
    assert result.error_code is None


@pytest.mark.asyncio
async def test_execute_unknown_tool() -> None:
    result = await ToolRegistry().execute("ghost", {})
    assert result.ok is False
    assert result.error_code == "unknown_tool"
    assert "ghost" in result.output


@pytest.mark.asyncio
async def test_execute_invalid_args_readable() -> None:
    registry = ToolRegistry()
    registry.register(_spec())
    result = await registry.execute("echo_text", {"text": "好", "times": 99})
    assert result.ok is False
    assert result.error_code == "invalid_args"
    assert "times" in result.output  # 可读中文指明字段


@pytest.mark.asyncio
async def test_execute_executor_exception_not_leaked() -> None:
    async def _boom(args: dict[str, Any]) -> str:  # pragma: no cover
        raise RuntimeError("磁盘炸了")

    registry = ToolRegistry()
    registry.register(_spec(executor=_boom))
    result = await registry.execute("echo_text", {"text": "好"})
    assert result.ok is False
    assert result.error_code == "execution_error"
    assert "echo_text" in result.output
    assert "磁盘炸了" in result.output
