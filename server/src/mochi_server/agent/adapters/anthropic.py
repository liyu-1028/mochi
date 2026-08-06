"""Anthropic 适配器（M1-S0，ADR-0002 D1 补齐）。

与 OpenAI 兼容接口差异大到不值得强行统一（ADR-0002 D1），独立实现：

- system prompt 是 ``messages.create`` 的顶层参数，不混在 messages 里；
- 流式事件模型不同：``content_block_delta`` 携带 ``text_delta`` /
  ``thinking_delta`` 两类增量——thinking 直接映射为协议 thinking.* 的源；
- 异常体系独立（同为 stainless 生成，类名与 OpenAI 系对齐但互不兼容）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

from ...config import ModelProviderConfig
from ...events import ErrorCode, ErrorPayload
from ...secrets import KeyStore
from ..errors import AgentError
from .base import ChatMessage, ProviderAdapter, StreamKind

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT_SECONDS = 60.0
# Anthropic 必填 max_tokens：对话回复 1024 足够，长文场景后续按模型配置放开
_DEFAULT_MAX_TOKENS = 1024


class AnthropicAdapter(ProviderAdapter):
    """AsyncAnthropic 封装：流式对话（含 thinking 流）+ 连通性测试 + 异常翻译。"""

    def __init__(
        self,
        provider_id: str,
        cfg: ModelProviderConfig,
        key_store: KeyStore,
        *,
        client: AsyncAnthropic | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._cfg = cfg
        self._client = client or self._build_client(provider_id, cfg, key_store)

    # -- 构造 ----------------------------------------------------------------

    @staticmethod
    def _build_client(
        provider_id: str, cfg: ModelProviderConfig, key_store: KeyStore
    ) -> AsyncAnthropic:
        api_key = key_store.get_key(provider_id)
        if not api_key:
            raise AgentError(
                ErrorPayload(
                    code=ErrorCode.MODEL_AUTH,
                    message="尚未配置 API Key",
                    retryable=False,
                    hint=f"请在设置中为「{cfg.display_name}」填入 API Key",
                )
            )
        # max_retries=0：错误即时翻译给用户（重试交由协议 retryable 语义）
        return AsyncAnthropic(
            api_key=api_key,
            base_url=cfg.base_url,  # None → SDK 默认官方端点
            max_retries=0,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )

    # -- ProviderAdapter -----------------------------------------------------

    async def stream_chat(
        self, messages: list[ChatMessage], *, run_id: str
    ) -> AsyncIterator[tuple[StreamKind, str]]:
        system_text, chat_messages = _split_system(messages)
        try:
            async with self._client.messages.stream(
                model=self._cfg.model,
                max_tokens=_DEFAULT_MAX_TOKENS,
                system=system_text or None,
                messages=chat_messages,
            ) as stream:
                async for event in stream:
                    if getattr(event, "type", None) != "content_block_delta":
                        continue
                    delta = event.delta
                    kind = getattr(delta, "type", None)
                    if kind == "text_delta" and getattr(delta, "text", ""):
                        yield "text", delta.text
                    elif kind == "thinking_delta" and getattr(delta, "thinking", ""):
                        yield "thinking", delta.thinking
        except AgentError:
            raise
        except Exception as exc:  # 适配层职责即收敛一切异常为 AgentError
            raise _translate_sdk_error(exc, model=self._cfg.model) from exc

    async def ping(self) -> tuple[bool, str]:
        """以最小请求验证 端点可达 + Key 有效 + 模型存在。"""
        try:
            async for _chunk in self.stream_chat(
                [{"role": "user", "content": "ping"}], run_id="ping"
            ):
                break  # 收到首个增量即确认可用
            return True, "连接成功"
        except AgentError as exc:
            return False, exc.payload.hint or exc.payload.message


# ---------------------------------------------------------------------------
# 消息形态转换
# ---------------------------------------------------------------------------


def _split_system(
    messages: list[ChatMessage],
) -> tuple[str, list[ChatMessage]]:
    """拆出 system（顶层参数）；合并连续同角色消息（Anthropic 要求角色交替）。"""
    system_parts: list[str] = []
    chat: list[ChatMessage] = []
    for msg in messages:
        if msg["role"] == "system":
            system_parts.append(msg["content"])
            continue
        if chat and chat[-1]["role"] == msg["role"]:
            chat[-1] = {"role": msg["role"], "content": chat[-1]["content"] + "\n" + msg["content"]}
        else:
            chat.append({"role": msg["role"], "content": msg["content"]})
    return "\n\n".join(system_parts), chat


# ---------------------------------------------------------------------------
# SDK 异常 → 协议错误码映射（与 openai_compat 对齐；协议文档 §7）
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
                hint="请检查模型名称是否正确",
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
    if isinstance(exc, APIStatusError) and exc.status_code == 402:
        # MiniMax 等兼容端点以 402 表示余额/配额不足（实测 2026-08-05）
        return AgentError(
            ErrorPayload(
                code=ErrorCode.MODEL_QUOTA,
                message="模型服务账户余额不足",
                retryable=False,
                hint="请到服务商控制台充值或检查套餐状态后重试",
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
                hint="请检查网络连接",
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
    return any(
        k in lowered
        for k in ("context_length", "context length", "maximum context", "prompt is too long")
    )
