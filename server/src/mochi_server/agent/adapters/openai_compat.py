"""OpenAI 兼容适配器：一个实现覆盖 OpenAI 兼容接口 + Ollama /v1（ADR-0002 D1）。

Ollama 特化（已知边界，ADR-0002「Ollama 已知边界差异」）：
- api_key 用占位符（AsyncOpenAI 要求非空）；
- base_url 自动补 ``/v1`` 后缀；
- context overflow 可能不走 HTTP 状态码而是 chunk 内 error 字段 → 防御性检测。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

from ...config import OLLAMA_DEFAULT_BASE_URL, ModelProviderConfig
from ...events import ErrorCode, ErrorPayload
from ...secrets import KeyStore
from ..errors import AgentError
from .base import ChatMessage, ProviderAdapter

logger = logging.getLogger(__name__)

OLLAMA_API_KEY_PLACEHOLDER = "ollama"
_OLLAMA_V1_SUFFIX = "/v1"
_REQUEST_TIMEOUT_SECONDS = 60.0


class OpenAICompatibleAdapter(ProviderAdapter):
    """AsyncOpenAI 封装：流式对话 + 连通性测试 + 异常翻译。"""

    def __init__(
        self,
        provider_id: str,
        cfg: ModelProviderConfig,
        key_store: KeyStore,
        *,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._cfg = cfg
        self._client = client or self._build_client(provider_id, cfg, key_store)

    # -- 构造 ----------------------------------------------------------------

    @staticmethod
    def _build_client(
        provider_id: str, cfg: ModelProviderConfig, key_store: KeyStore
    ) -> AsyncOpenAI:
        if cfg.kind == "ollama":
            api_key = OLLAMA_API_KEY_PLACEHOLDER
            base_url = _ollama_v1_url(cfg.base_url)
        else:
            api_key_value = key_store.get_key(provider_id)
            if not api_key_value:
                raise AgentError(
                    ErrorPayload(
                        code=ErrorCode.MODEL_AUTH,
                        message="尚未配置 API Key",
                        retryable=False,
                        hint=f"请在设置中为「{cfg.display_name}」填入 API Key",
                    )
                )
            api_key = api_key_value
            base_url = cfg.base_url  # None → SDK 默认 OpenAI 官方端点
        # max_retries=0：错误即时翻译给用户（重试交由协议 retryable 语义）
        return AsyncOpenAI(
            api_key=api_key, base_url=base_url, max_retries=0, timeout=_REQUEST_TIMEOUT_SECONDS
        )

    # -- ProviderAdapter -----------------------------------------------------

    async def stream_chat(self, messages: list[ChatMessage], *, run_id: str) -> AsyncIterator[str]:
        try:
            stream = await self._client.chat.completions.create(
                model=self._cfg.model,
                messages=messages,
                stream=True,
                # 不传 stream_options 等扩展字段：Ollama /v1 兼容层支持滞后
            )
            async for chunk in stream:
                chunk_error = _chunk_error_text(chunk)
                if chunk_error:
                    raise _translate_chunk_error(chunk_error, model=self._cfg.model)
                if not chunk.choices:
                    continue
                content = chunk.choices[0].delta.content
                if content:
                    yield content
        except AgentError:
            raise
        except Exception as exc:  # 适配层职责即收敛一切异常为 AgentError
            raise _translate_sdk_error(exc, model=self._cfg.model) from exc

    async def ping(self) -> tuple[bool, str]:
        """以最小补全请求验证 端点可达 + Key 有效 + 模型存在。"""
        try:
            async for _chunk in self.stream_chat(
                [{"role": "user", "content": "ping"}], run_id="ping"
            ):
                break  # 收到首个增量即确认可用
            return True, "连接成功"
        except AgentError as exc:
            return False, exc.payload.hint or exc.payload.message


# ---------------------------------------------------------------------------
# Ollama 特化辅助
# ---------------------------------------------------------------------------


def _ollama_v1_url(base_url: str | None) -> str:
    url = (base_url or OLLAMA_DEFAULT_BASE_URL).rstrip("/")
    return url if url.endswith(_OLLAMA_V1_SUFFIX) else url + _OLLAMA_V1_SUFFIX


def _chunk_error_text(chunk: Any) -> str | None:
    """防御性检测流内 error 字段（Ollama 部分错误不走 HTTP 状态码）。"""
    extra = getattr(chunk, "model_extra", None)
    error = (extra or {}).get("error") if isinstance(extra, dict) else None
    if error is None:
        error = getattr(chunk, "error", None)
    if error is None:
        return None
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error)


def _translate_chunk_error(message: str, *, model: str) -> AgentError:
    lowered = message.lower()
    if "context" in lowered or "token" in lowered:
        return AgentError(
            ErrorPayload(
                code=ErrorCode.CONTEXT_OVERFLOW,
                message="对话过长，模型装不下了",
                retryable=False,
                hint="请新开会话，或换上下文更大的模型",
            )
        )
    return AgentError(
        ErrorPayload(
            code=ErrorCode.MODEL_UNAVAILABLE,
            message=f"模型 {model} 返回了错误",
            retryable=True,
            hint=message,
        )
    )


# ---------------------------------------------------------------------------
# SDK 异常 → 协议错误码映射（协议文档 §7；文案要求见功能清单 6.7）
# ---------------------------------------------------------------------------


def _translate_sdk_error(exc: Exception, *, model: str) -> AgentError:
    # 注意顺序：特化子类在前，APIStatusError/APIConnectionError 基类兜底在后
    if isinstance(exc, AuthenticationError):  # 401
        return AgentError(
            ErrorPayload(
                code=ErrorCode.MODEL_AUTH,
                message="模型授权失败",
                retryable=False,
                hint="请检查 API Key 是否正确，可在设置中重新输入",
            )
        )
    if isinstance(exc, PermissionDeniedError):  # 403
        return AgentError(
            ErrorPayload(
                code=ErrorCode.MODEL_AUTH,
                message="账号无权访问该模型",
                retryable=False,
                hint="请确认账号已开通该模型的访问权限",
            )
        )
    if isinstance(exc, NotFoundError):  # 404
        return AgentError(
            ErrorPayload(
                code=ErrorCode.MODEL_UNAVAILABLE,
                message=f"模型 {model} 不存在",
                retryable=False,
                hint="请检查模型名称；Ollama 用户可先执行 ollama pull 拉取模型",
            )
        )
    if isinstance(exc, RateLimitError):  # 429
        return AgentError(
            ErrorPayload(
                code=ErrorCode.MODEL_RATE_LIMIT,
                message="请求太频繁了",
                retryable=True,
                hint="请稍等片刻再试",
            )
        )
    if isinstance(exc, APITimeoutError):  # APITimeoutError 是 APIConnectionError 子类
        return AgentError(
            ErrorPayload(
                code=ErrorCode.NETWORK,
                message="连接模型超时",
                retryable=True,
                hint="请检查网络连接，或确认 base_url 是否正确",
            )
        )
    if isinstance(exc, APIConnectionError):
        return AgentError(
            ErrorPayload(
                code=ErrorCode.NETWORK,
                message="无法连接到模型服务",
                retryable=True,
                hint="请检查网络；本地模型请确认服务已启动",
            )
        )
    if isinstance(exc, BadRequestError):  # 400
        if _looks_like_context_overflow(str(exc)):
            return AgentError(
                ErrorPayload(
                    code=ErrorCode.CONTEXT_OVERFLOW,
                    message="对话过长，模型装不下了",
                    retryable=False,
                    hint="请新开会话，或换上下文更大的模型",
                )
            )
        return AgentError(
            ErrorPayload(
                code=ErrorCode.INTERNAL,
                message="模型拒绝了这次请求",
                retryable=False,
                hint="请稍后再试，或检查模型配置",
            )
        )
    if isinstance(exc, APIStatusError) and exc.status_code >= 500:
        return AgentError(
            ErrorPayload(
                code=ErrorCode.MODEL_UNAVAILABLE,
                message="模型服务暂时不可用",
                retryable=True,
                hint="服务端繁忙，请稍后再试",
            )
        )
    # 兜底前的最后甄别：部分后端（如 Ollama）把 context overflow 以裸异常形式抛出
    if _looks_like_context_overflow(str(exc)):
        return AgentError(
            ErrorPayload(
                code=ErrorCode.CONTEXT_OVERFLOW,
                message="对话过长，模型装不下了",
                retryable=False,
                hint="请新开会话，或换上下文更大的模型",
            )
        )
    logger.warning("未分类的模型调用异常：%s", exc)
    return AgentError(
        ErrorPayload(
            code=ErrorCode.INTERNAL,
            message="我这边出了点小状况，请再试一次",
            retryable=True,
        )
    )


def _looks_like_context_overflow(text: str) -> bool:
    lowered = text.lower()
    return any(k in lowered for k in ("context_length", "context length", "maximum context"))
