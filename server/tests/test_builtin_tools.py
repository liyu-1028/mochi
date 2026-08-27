"""内置工具集测试（M1-S4 任务 9，ADR-0008 D5）：行为、护栏、装配。

覆盖：
- get_current_time：格式/星期/时区偏移/越界参数收敛为 invalid_args；
- read_text_file：正常读取、不存在、目录、二进制拒绝、非 UTF-8、截断注记；
- register_builtin_tools：注册清单、danger 分级、重名防重；
- ProviderRegistry 装配：进程级注册表出厂即含内置工具。
"""

from __future__ import annotations

import re

import pytest

from mochi_server.agent import (
    DangerLevel,
    ProviderRegistry,
    ToolRegistry,
    ToolRegistryError,
    register_builtin_tools,
)
from mochi_server.config import AppConfig, ModelConfig
from mochi_server.secrets import KeyStore


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry


# ---------------------------------------------------------------------------
# get_current_time（safe）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_current_time_format_and_weekday() -> None:
    result = await _registry().execute("get_current_time", {})
    assert result.ok
    # 2026-08-19 14:30:25 星期三 UTC+00:00
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} 星期[一二三四五六日] UTC[+-]\d{2}:\d{2}",
        result.output,
    )


@pytest.mark.asyncio
async def test_current_time_tz_offset() -> None:
    result = await _registry().execute("get_current_time", {"tz_offset_minutes": 480})
    assert result.ok
    assert "UTC+08:00" in result.output


@pytest.mark.asyncio
async def test_current_time_rejects_out_of_range_offset() -> None:
    result = await _registry().execute("get_current_time", {"tz_offset_minutes": 999})
    assert not result.ok
    assert result.error_code == "invalid_args"
    assert "tz_offset_minutes" in result.output


# ---------------------------------------------------------------------------
# read_text_file（dangerous）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_text_file_roundtrip(tmp_path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("你好，Mochi！", encoding="utf-8")
    result = await _registry().execute("read_text_file", {"path": str(target)})
    assert result.ok
    assert result.output == "你好，Mochi！"


@pytest.mark.asyncio
async def test_read_text_file_expands_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "h.txt").write_text("home content", encoding="utf-8")
    result = await _registry().execute("read_text_file", {"path": "~/h.txt"})
    assert result.ok
    assert result.output == "home content"


@pytest.mark.asyncio
async def test_read_text_file_missing() -> None:
    result = await _registry().execute("read_text_file", {"path": "/nonexistent/mochi.txt"})
    assert not result.ok
    assert result.error_code == "execution_error"
    assert "文件不存在" in result.output


@pytest.mark.asyncio
async def test_read_text_file_directory_rejected(tmp_path) -> None:
    result = await _registry().execute("read_text_file", {"path": str(tmp_path)})
    assert not result.ok
    assert "不是普通文件" in result.output


@pytest.mark.asyncio
async def test_read_text_file_binary_rejected(tmp_path) -> None:
    target = tmp_path / "blob.bin"
    target.write_bytes(b"MZ\x00\x00\x00binary payload")
    result = await _registry().execute("read_text_file", {"path": str(target)})
    assert not result.ok
    assert "二进制" in result.output


@pytest.mark.asyncio
async def test_read_text_file_non_utf8_rejected(tmp_path) -> None:
    # GBK 编码的中文字节流：无 NUL，但 UTF-8 解码必败
    target = tmp_path / "gbk.txt"
    target.write_bytes("你好".encode("gbk"))
    result = await _registry().execute("read_text_file", {"path": str(target)})
    assert not result.ok
    assert "UTF-8" in result.output


@pytest.mark.asyncio
async def test_read_text_file_truncation_note(tmp_path, monkeypatch) -> None:
    import mochi_server.agent.tools.builtin as builtin

    target = tmp_path / "big.txt"
    target.write_text("A" * 100, encoding="utf-8")
    monkeypatch.setattr(builtin, "_MAX_FILE_BYTES", 10)
    result = await _registry().execute("read_text_file", {"path": str(target)})
    assert result.ok
    assert result.output.startswith("A" * 10)
    assert "仅返回前 10 字节" in result.output


# ---------------------------------------------------------------------------
# 注册与装配
# ---------------------------------------------------------------------------


def test_register_builtin_levels_and_names() -> None:
    registry = _registry()
    names = [spec.name for spec in registry.list_specs()]
    assert names == ["get_current_time", "read_text_file"]
    assert registry.get("get_current_time").danger is DangerLevel.SAFE
    assert registry.get("read_text_file").danger is DangerLevel.DANGEROUS


def test_register_builtin_rejects_duplicate() -> None:
    registry = _registry()
    with pytest.raises(ToolRegistryError, match="重复注册"):
        register_builtin_tools(registry)


def test_langchain_tools_declares_all() -> None:
    tools = _registry().langchain_tools()
    assert [t.name for t in tools] == ["get_current_time", "read_text_file"]


def test_provider_registry_assembles_builtins() -> None:
    config = AppConfig(model=ModelConfig(default_provider="trial", providers={}))
    registry = ProviderRegistry(config, KeyStore())
    assert registry.tool_registry.get("get_current_time") is not None
    assert registry.tool_registry.get("read_text_file") is not None
