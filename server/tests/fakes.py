"""测试假模型与共用构造器（M1-S4 图内核）。

ScriptedChatModel：按「每次调用一个剧本」驱动 ReAct 图/事件桥——
每次 _astream/_generate 消耗下一个剧本（AIMessageChunk 序列或 Exception），
并录制收到的消息（received[0] 为首轮输入，received[1] 含 ToolMessage
回灌，适配回环断言）。bind_tools 返回自身并记录工具名（声明轨不真实
生效——是否调用工具由剧本直接给出）。

与 test_langchain_adapter.ScriptedModel 的分工：那个是单剧本重放（适配器
层单轮），本件是多回合剧本（图回环）。
"""

from __future__ import annotations

from typing import Any

import httpx
import openai
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from mochi_server.agent.adapters.langchain import LangChainAdapter
from mochi_server.config import ModelProviderConfig
from mochi_server.secrets import KeyStore


class ScriptedChatModel(BaseChatModel):
    calls: list[list[Any]] = Field(default_factory=list)
    received: list[list[Any]] = Field(default_factory=list)
    bound_tool_names: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        self.bound_tool_names = [t.name for t in tools]
        return self

    def _current_script(self) -> list[Any]:
        if self.call_index >= len(self.calls):
            raise AssertionError(f"剧本耗尽：第 {self.call_index + 1} 次模型调用无剧本")
        return self.calls[self.call_index]

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.received.append(list(messages))
        script = self._current_script()
        self.call_index += 1
        for item in script:
            if isinstance(item, Exception):
                raise item
        texts = "".join(
            c.content
            for c in script
            if isinstance(c, AIMessageChunk) and isinstance(c.content, str)
        )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=texts))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        self.received.append(list(messages))
        script = self._current_script()
        self.call_index += 1
        for item in script:
            if isinstance(item, Exception):
                raise item
            yield ChatGenerationChunk(message=item)

    # pydantic 可变计数器（未声明为字段，运行时 setattr）
    call_index: int = 0


def make_test_adapter(model: BaseChatModel, *, kind: str = "openai_compatible") -> LangChainAdapter:
    """注入假模型的 LangChainAdapter（key 无关——model 已注入）。"""
    cfg = ModelProviderConfig(
        kind=kind,  # type: ignore[arg-type]
        display_name="测试",
        base_url="https://api.example.com/v1",
        model="test-model",
    )
    return LangChainAdapter("test", cfg, KeyStore(), model=model)


def sdk_error(cls: type[Exception], status: int, message: str) -> Exception:
    """构造 openai 族 SDK 异常（供剧本抛出，验证图内核错误收敛）。"""
    body = {"error": {"message": message, "type": "invalid_request_error"}}
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    if cls is openai.APITimeoutError or cls is openai.APIConnectionError:
        return cls(request=request)  # type: ignore[call-arg]
    return cls(message, response=httpx.Response(status, json=body, request=request), body=body)
