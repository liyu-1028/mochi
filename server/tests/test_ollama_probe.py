"""Ollama 探测测试（httpx.MockTransport 注入）。"""

from __future__ import annotations

import httpx
import pytest

from mochi_server.agent.ollama_probe import probe_ollama

_BASE = "http://127.0.0.1:11434"


@pytest.mark.asyncio
async def test_probe_success_lists_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}, {"name": "llama3.2:3b"}]})

    result = await probe_ollama(_BASE, transport=httpx.MockTransport(handler))
    assert result.available is True
    assert result.models == ["qwen3:8b", "llama3.2:3b"]
    assert result.error_hint is None


@pytest.mark.asyncio
async def test_probe_filters_embedding_only_models() -> None:
    """bge-m3 这类 embedding 模型不能对话，不应进入默认配置候选。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "bge-m3:latest", "capabilities": ["embedding"]},
                    {"name": "qwen2.5:1.5b", "capabilities": ["completion", "tools"]},
                    {"name": "legacy:7b"},  # 旧版 Ollama 无 capabilities 字段 → 保守保留
                ]
            },
        )

    result = await probe_ollama(_BASE, transport=httpx.MockTransport(handler))
    assert result.models == ["qwen2.5:1.5b", "legacy:7b"]


@pytest.mark.asyncio
async def test_probe_connection_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    result = await probe_ollama(_BASE, transport=httpx.MockTransport(handler))
    assert result.available is False
    assert result.models == []
    assert result.error_hint  # 有引导文案（功能清单 6.3：未安装时给出引导）


@pytest.mark.asyncio
async def test_probe_timeout_treated_as_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    result = await probe_ollama(_BASE, timeout=0.01, transport=httpx.MockTransport(handler))
    assert result.available is False


@pytest.mark.asyncio
async def test_probe_malformed_json_treated_as_unavailable() -> None:
    result = await probe_ollama(
        _BASE,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"not-json")),
    )
    assert result.available is False
    assert result.error_hint
