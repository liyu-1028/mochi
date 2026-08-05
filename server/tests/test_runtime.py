"""runtime.json 端口发现测试（M1-S0）：写入/删除、端口解析。"""

from __future__ import annotations

import json

import pytest

from mochi_server import runtime
from mochi_server.events import PROTOCOL_VERSION


def test_resolve_port_default() -> None:
    assert runtime.resolve_port() == runtime.DEFAULT_PORT


def test_resolve_port_from_env(monkeypatch) -> None:
    monkeypatch.setenv(runtime.PORT_ENV, "9321")
    assert runtime.resolve_port() == 9321


def test_resolve_port_invalid_env_falls_back(monkeypatch) -> None:
    monkeypatch.setenv(runtime.PORT_ENV, "not-a-port")
    assert runtime.resolve_port() == runtime.DEFAULT_PORT


def test_write_and_read_runtime_file(monkeypatch) -> None:
    monkeypatch.setenv(runtime.PORT_ENV, "9321")
    runtime.write_runtime_file(runtime.resolve_port())

    data = json.loads(runtime.get_runtime_path().read_text(encoding="utf-8"))
    assert data["port"] == 9321
    assert data["protocolVersion"] == PROTOCOL_VERSION
    assert isinstance(data["pid"], int) and data["pid"] > 0
    assert isinstance(data["startedAt"], int) and data["startedAt"] > 0


def test_write_overwrites_previous(monkeypatch) -> None:
    runtime.write_runtime_file(8199)
    runtime.write_runtime_file(9001)
    data = json.loads(runtime.get_runtime_path().read_text(encoding="utf-8"))
    assert data["port"] == 9001


def test_remove_runtime_file_idempotent() -> None:
    runtime.write_runtime_file(8199)
    runtime.remove_runtime_file()
    assert not runtime.get_runtime_path().exists()
    runtime.remove_runtime_file()  # 二次删除不抛异常


@pytest.mark.asyncio
async def test_lifespan_writes_and_removes_runtime_file() -> None:
    """端到端：TestClient 生命周期内 runtime.json 出现又消失。"""
    from fastapi.testclient import TestClient

    from mochi_server.agent import EchoAgentService
    from mochi_server.main import create_app

    with TestClient(create_app(EchoAgentService())) as client:
        assert client.get("/health").status_code == 200
        assert runtime.get_runtime_path().exists()
    assert not runtime.get_runtime_path().exists()
