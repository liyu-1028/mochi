"""Ollama 连通性探测（config-format.md §6 Zero Config 关键路径）。

探测原生接口 ``/api/tags``（比 /v1/models 稳），1.5s 硬超时——
结果同时服务：首次启动默认配置生成、前端引导分支、ollama-status 端点。
"""

from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel

from ..config import OLLAMA_DEFAULT_BASE_URL

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 1.5

_OLLAMA_NOT_RUNNING_HINT = "未检测到 Ollama：如未安装请访问 ollama.com 下载；已安装请确认它正在运行"


class OllamaProbeResult(BaseModel):
    available: bool
    models: list[str] = []
    error_hint: str | None = None


async def probe_ollama(
    base_url: str = OLLAMA_DEFAULT_BASE_URL,
    *,
    timeout: float = PROBE_TIMEOUT_SECONDS,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OllamaProbeResult:
    """探测本地 Ollama；任何失败都按「不可用」处理，绝不抛错阻塞启动。"""
    url = base_url.rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.info("Ollama 探测失败：%s", exc)
        return OllamaProbeResult(available=False, error_hint=_OLLAMA_NOT_RUNNING_HINT)

    try:
        models = [str(m["name"]) for m in resp.json().get("models", [])]
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("Ollama /api/tags 响应异常：%s", exc)
        return OllamaProbeResult(available=False, error_hint="Ollama 响应格式异常，请检查其版本")
    return OllamaProbeResult(available=True, models=models)
