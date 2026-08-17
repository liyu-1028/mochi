"""LangChain 适配器（M1-S4，ADR-0008 D2）：模型 I/O 迁至 langchain 封装。

langchain-anthropic / langchain-openai 白拿 tool-call 跨家归一（任务 5 图内核
消费）；本层保持 ProviderAdapter 接口不变——LLMAgentService / MemoryManager /
RunManager 零改动，任务 5 换内核时整体溶解本适配层。

- ollama 沿用 ChatOpenAI + /v1 通道（v0.1.x 行为零变更，不用 ChatOllama；
  langchain-ollama 留作后续评估）
- thinking 增量：anthropic 流式以 content 块 ``type=thinking`` 暴露（spike 实证，
  ADR-0008 附注）；OpenAI 兼容路径恒 text（与旧适配器一致）
- 空流守卫：Ollama 流内 error 字段经 LC 归一化后丢失（旧 _chunk_error_text
  防御不再可行），流结束零增量时以可读 AgentError 兜底
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

import anthropic
import openai
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ...config import OLLAMA_DEFAULT_BASE_URL, ModelProviderConfig
from ...events import ErrorCode, ErrorPayload
from ...secrets import KeyStore
from ..errors import AgentError
from .base import ChatMessage, ProviderAdapter, StreamKind

logger = logging.getLogger(__name__)

OLLAMA_API_KEY_PLACEHOLDER = "ollama"
_OLLAMA_V1_SUFFIX = "/v1"
_REQUEST_TIMEOUT_SECONDS = 60.0
_DEFAULT_MAX_TOKENS = 1024  # Anthropic 必填 max_tokens；OpenAI 侧不设（行为同旧版）


def _ollama_v1_url(base_url: str | None) -> str:
    url = (base_url or OLLAMA_DEFAULT_BASE_URL).rstrip("/")
    return url if url.endswith(_OLLAMA_V1_SUFFIX) else url + _OLLAMA_V1_SUFFIX


def _require_key(provider_id: str, cfg: ModelProviderConfig, key_store: KeyStore) -> str:
    """云端提供方构造期取 Key；缺失即抛 AgentError（由 RunManager 转 run.error）。"""
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
    return api_key


def build_chat_model(
    provider_id: str, cfg: ModelProviderConfig, key_store: KeyStore
) -> BaseChatModel:
    """按 provider 配置构造 langchain 模型实例（ADR-0008 D2 工厂）。

    max_retries=0：错误即时翻译给用户（重试交由协议 retryable 语义），与旧
    适配器一致。
    """
    if cfg.kind == "anthropic":
        return ChatAnthropic(
            model=cfg.model,
            api_key=_require_key(provider_id, cfg, key_store),
            base_url=cfg.base_url,  # None → SDK 默认官方端点
            max_tokens=_DEFAULT_MAX_TOKENS,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )
    if cfg.kind == "ollama":
        api_key = OLLAMA_API_KEY_PLACEHOLDER  # ChatOpenAI 要求非空
        base_url = _ollama_v1_url(cfg.base_url)
    else:  # openai_compatible
        api_key = _require_key(provider_id, cfg, key_store)
        base_url = cfg.base_url  # None → SDK 默认 OpenAI 官方端点
    return ChatOpenAI(
        model=cfg.model,
        api_key=api_key,
        base_url=base_url,
        timeout=_REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )


class LangChainAdapter(ProviderAdapter):
    """langchain 模型封装：流式对话（含 thinking 流）+ 连通性测试 + 异常翻译。"""

    def __init__(
        self,
        provider_id: str,
        cfg: ModelProviderConfig,
        key_store: KeyStore,
        *,
        model: BaseChatModel | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._cfg = cfg
        # model 注入缝：测试注入 fake/mock 模型，绕开 LC 无 client 注入缝的路径
        self._model = model or build_chat_model(provider_id, cfg, key_store)

    @property
    def chat_model(self) -> BaseChatModel:
        """底层 langchain 模型（任务 5 图内核 bind_tools 取用）。"""
        return self._model

    # -- ProviderAdapter -----------------------------------------------------

    async def stream_chat(
        self, messages: list[ChatMessage], *, run_id: str
    ) -> AsyncIterator[tuple[StreamKind, str]]:
        got_any = False
        try:
            lc_messages = _to_lc_messages(messages, anthropic_style=self._cfg.kind == "anthropic")
            async for chunk in self._model.astream(lc_messages):
                for kind, delta in _deltas_from_chunk(chunk):
                    got_any = True
                    yield kind, delta
        except AgentError:
            raise
        except Exception as exc:  # 适配层职责即收敛一切异常为 AgentError
            raise _translate_sdk_error(exc, model=self._cfg.model) from exc
        if not got_any:
            # 空流守卫：补偿 Ollama 流内 error 字段经 LC 归一化丢失的退化
            raise AgentError(
                ErrorPayload(
                    code=ErrorCode.MODEL_UNAVAILABLE,
                    message="模型没有返回任何内容",
                    retryable=True,
                    hint="本地模型请确认已拉取并加载（ollama pull / ollama run），云端模型请稍后再试",
                )
            )

    async def ping(self) -> tuple[bool, str]:
        """以最小补全请求验证 端点可达 + Key 有效 + 模型存在。"""
        try:
            await self._model.ainvoke([HumanMessage(content="ping")])
        except Exception as exc:
            err = (
                exc
                if isinstance(exc, AgentError)
                else _translate_sdk_error(exc, model=self._cfg.model)
            )
            return False, err.payload.hint or err.payload.message
        return True, "连接成功"


# ---------------------------------------------------------------------------
# 消息形态转换
# ---------------------------------------------------------------------------

_ROLE_TO_CLS = {"system": SystemMessage, "user": HumanMessage, "assistant": AIMessage}


def _to_lc_messages(messages: list[ChatMessage], *, anthropic_style: bool) -> list[Any]:
    """ChatMessage dict → langchain 消息。

    anthropic_style：合并连续同角色消息（Anthropic 要求角色交替；SystemMessage
    由 langchain-anthropic 自动提为顶层 system 参数，不参与合并）。移植自旧
    AnthropicAdapter._split_system，行为一致。
    """
    out: list[Any] = []
    for msg in messages:
        cls = _ROLE_TO_CLS[msg["role"]]
        if anthropic_style and out and type(out[-1]) is cls and cls is not SystemMessage:
            out[-1] = cls(content=out[-1].content + "\n" + msg["content"])
        else:
            out.append(cls(content=msg["content"]))
    return out


def _deltas_from_chunk(chunk: Any) -> Iterator[tuple[StreamKind, str]]:
    """LC 流式 chunk → (kind, delta) 增量。

    content 为 str（OpenAI 兼容）→ text；为 list（anthropic）→ 按块 type 分拣
    text / thinking（spike 实证，ADR-0008 附注）。注意线上格式的文本键不同：
    text 块在 ``text``、thinking 块在 ``thinking``（实测键序
    ``['index', 'thinking', 'type']``，2026-08-18）。tool_call_chunks 本任务不消费。
    """
    content = chunk.content
    if isinstance(content, str):
        if content:
            yield "text", content
        return
    for block in content:
        btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        if btype not in ("text", "thinking"):
            continue
        key = "text" if btype == "text" else "thinking"
        raw = block.get(key) if isinstance(block, dict) else getattr(block, key, "")
        if raw:
            yield btype, raw


# ---------------------------------------------------------------------------
# SDK 异常 → 协议错误码映射（协议文档 §7；文案要求见功能清单 6.7）
# 两族 stainless 异常类名相同、互不兼容，元组并集统一翻译（语义与旧版逐条对齐）
# ---------------------------------------------------------------------------

_AUTH_ERRORS = (openai.AuthenticationError, anthropic.AuthenticationError)
_PERMISSION_ERRORS = (openai.PermissionDeniedError, anthropic.PermissionDeniedError)
_NOT_FOUND_ERRORS = (openai.NotFoundError, anthropic.NotFoundError)
_RATE_LIMIT_ERRORS = (openai.RateLimitError, anthropic.RateLimitError)
_TIMEOUT_ERRORS = (openai.APITimeoutError, anthropic.APITimeoutError)
_CONNECTION_ERRORS = (openai.APIConnectionError, anthropic.APIConnectionError)
_BAD_REQUEST_ERRORS = (openai.BadRequestError, anthropic.BadRequestError)
_STATUS_ERRORS = (openai.APIStatusError, anthropic.APIStatusError)


def _translate_sdk_error(exc: Exception, *, model: str) -> AgentError:
    # 注意顺序：特化子类在前，APIStatusError/APIConnectionError 基类兜底在后
    if isinstance(exc, _AUTH_ERRORS):  # 401
        return AgentError(
            ErrorPayload(
                code=ErrorCode.MODEL_AUTH,
                message="模型授权失败",
                retryable=False,
                hint="请检查 API Key 是否正确，可在设置中重新输入",
            )
        )
    if isinstance(exc, _PERMISSION_ERRORS):  # 403
        return AgentError(
            ErrorPayload(
                code=ErrorCode.MODEL_AUTH,
                message="账号无权访问该模型",
                retryable=False,
                hint="请确认账号已开通该模型的访问权限",
            )
        )
    if isinstance(exc, _NOT_FOUND_ERRORS):  # 404
        # OpenAI 系还承载 Ollama /v1，404 多为模型未拉取，hint 附引导
        openai_family = isinstance(exc, openai.NotFoundError)
        hint = (
            "请检查模型名称；Ollama 用户可先执行 ollama pull 拉取模型"
            if openai_family
            else "请检查模型名称是否正确"
        )
        return AgentError(
            ErrorPayload(
                code=ErrorCode.MODEL_UNAVAILABLE,
                message=f"模型 {model} 不存在",
                retryable=False,
                hint=hint,
            )
        )
    if isinstance(exc, _RATE_LIMIT_ERRORS):  # 429
        return AgentError(
            ErrorPayload(
                code=ErrorCode.MODEL_RATE_LIMIT,
                message="请求太频繁了",
                retryable=True,
                hint="请稍等片刻再试",
            )
        )
    if isinstance(exc, _TIMEOUT_ERRORS):  # APITimeoutError 是 APIConnectionError 子类
        return AgentError(
            ErrorPayload(
                code=ErrorCode.NETWORK,
                message="连接模型超时",
                retryable=True,
                hint="请检查网络连接，或确认 base_url 是否正确",
            )
        )
    if isinstance(exc, _CONNECTION_ERRORS):
        return AgentError(
            ErrorPayload(
                code=ErrorCode.NETWORK,
                message="无法连接到模型服务",
                retryable=True,
                hint="请检查网络；本地模型请确认服务已启动",
            )
        )
    if isinstance(exc, _BAD_REQUEST_ERRORS):  # 400
        if _looks_like_context_overflow(str(exc)):
            return _context_overflow_error()
        return AgentError(
            ErrorPayload(
                code=ErrorCode.INTERNAL,
                message="模型拒绝了这次请求",
                retryable=False,
                hint="请稍后再试，或检查模型配置",
            )
        )
    if isinstance(exc, _STATUS_ERRORS):
        if exc.status_code == 402:
            # MiniMax 等兼容端点以 402 表示余额/配额不足（实测 2026-08-05）
            return AgentError(
                ErrorPayload(
                    code=ErrorCode.MODEL_QUOTA,
                    message="模型服务账户余额不足",
                    retryable=False,
                    hint="请到服务商控制台充值或检查套餐状态后重试",
                )
            )
        if exc.status_code >= 500:
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
        return _context_overflow_error()
    logger.warning("未分类的模型调用异常：%s", exc)
    return AgentError(
        ErrorPayload(
            code=ErrorCode.INTERNAL,
            message="我这边出了点小状况，请再试一次",
            retryable=True,
        )
    )


def _context_overflow_error() -> AgentError:
    return AgentError(
        ErrorPayload(
            code=ErrorCode.CONTEXT_OVERFLOW,
            message="对话过长，模型装不下了",
            retryable=False,
            hint="请新开会话，或换上下文更大的模型",
        )
    )


def _looks_like_context_overflow(text: str) -> bool:
    lowered = text.lower()
    return any(
        k in lowered
        for k in ("context_length", "context length", "maximum context", "prompt is too long")
    )
