"""Mochi Agent 事件协议 v0.1 —— Python 侧镜像定义。

规范文档：docs/protocol/agent-events-v0.1.md
前端事实源：packages/protocol/src/index.ts

⚠️ 本文件必须与 TS 定义保持逐字段一致。0.x 阶段人工同步；
一致性黄金样例：packages/protocol/testdata/turn-with-tool-call.jsonl

序列化约定：协议负载一律 camelCase。数据模型继承 CamelModel，
snake_case 字段经 alias_generator 自动映射 camelCase（双向）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

PROTOCOL_VERSION = "0.1"
SERVER_NAME = "mochi-server"


class CamelModel(BaseModel):
    """协议负载基类：Python 用 snake_case 构造，线上格式为 camelCase。"""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------
class Emotion(StrEnum):
    """Mochi 扩展：角色情绪（功能清单 2.5，≥5 种）。"""

    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    CONFUSED = "confused"
    SURPRISED = "surprised"
    EMBARRASSED = "embarrassed"
    ANGRY = "angry"


class CharacterState(StrEnum):
    """Mochi 扩展：角色动画状态机状态（功能清单 2.2，6 状态）。"""

    IDLE = "idle"
    TALKING = "talking"
    THINKING = "thinking"
    WORKING = "working"
    ERROR = "error"
    SLEEPING = "sleeping"


class ErrorCode(StrEnum):
    """标准化错误码（规范文档 §7）。"""

    VERSION_MISMATCH = "ERR_VERSION_MISMATCH"
    MODEL_AUTH = "ERR_MODEL_AUTH"
    MODEL_UNAVAILABLE = "ERR_MODEL_UNAVAILABLE"
    MODEL_RATE_LIMIT = "ERR_MODEL_RATE_LIMIT"
    MODEL_QUOTA = "ERR_MODEL_QUOTA"
    NETWORK = "ERR_NETWORK"
    CONTEXT_OVERFLOW = "ERR_CONTEXT_OVERFLOW"
    TOOL_DENIED = "ERR_TOOL_DENIED"
    TOOL_FAILED = "ERR_TOOL_FAILED"
    CANCELLED = "ERR_CANCELLED"
    INTERNAL = "ERR_INTERNAL"


RunFinishReason = Literal["complete", "cancelled", "interrupted", "error"]
ToolCallStatus = Literal["success", "error", "denied"]


# ---------------------------------------------------------------------------
# 信封与公共结构
# ---------------------------------------------------------------------------
class Envelope(BaseModel):
    """通用信封：所有 WebSocket JSON 帧共享的外层结构（字段本身即 camelCase 安全）。"""

    v: str = PROTOCOL_VERSION
    type: str
    id: str = Field(default_factory=lambda: str(uuid4()))
    ts: int  # 毫秒级 Unix 时间戳，发送时填充
    data: dict[str, Any] = Field(default_factory=dict)


class ErrorPayload(CamelModel):
    code: str
    message: str  # 用户可读文案，禁止裸露堆栈（功能清单 6.7）
    retryable: bool = False
    hint: str | None = None


class ClientInfo(CamelModel):
    """hello 命令中的客户端标识。"""

    name: str
    version: str


class ServerInfo(CamelModel):
    """hello_ack 事件中的服务端标识。"""

    name: str
    version: str


class UsageInfo(CamelModel):
    """run.finished 的 token 用量（可选）。"""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def make_frame(event_type: str, data: CamelModel | dict[str, Any], ts: int) -> dict[str, Any]:
    """构建可直接 send_json 的完整帧（负载模型自动转 camelCase dict）。"""
    payload = (
        data.model_dump(by_alias=True, exclude_none=True) if isinstance(data, BaseModel) else data
    )
    return Envelope(type=event_type, ts=ts, data=payload).model_dump()


# ---------------------------------------------------------------------------
# 客户端 → 服务端命令负载
# ---------------------------------------------------------------------------
class HelloData(CamelModel):
    versions: list[str]
    client: ClientInfo


class PingData(CamelModel):
    token: str | None = None


class Attachment(CamelModel):
    kind: Literal["image", "file"]
    path: str
    name: str


class ChatSendData(CamelModel):
    run_id: str
    session_id: str
    text: str
    attachments: list[Attachment] | None = None


class ChatCancelData(CamelModel):
    run_id: str


class ChatInterruptData(CamelModel):
    run_id: str


# ---------------------------------------------------------------------------
# 服务端 → 客户端事件负载
# ---------------------------------------------------------------------------
class HelloAckData(CamelModel):
    version: str
    server: ServerInfo


class HelloErrorData(CamelModel):
    error: ErrorPayload


class PongData(CamelModel):
    token: str | None = None


class RunStartedData(CamelModel):
    run_id: str
    session_id: str


class RunFinishedData(CamelModel):
    run_id: str
    reason: RunFinishReason
    usage: UsageInfo | None = None


class RunErrorData(CamelModel):
    run_id: str
    error: ErrorPayload


class TextStartData(CamelModel):
    run_id: str
    message_id: str
    role: Literal["assistant"] = "assistant"


class TextDeltaData(CamelModel):
    run_id: str
    message_id: str
    delta: str


class TextEndData(CamelModel):
    run_id: str
    message_id: str
    full_text: str


class ThinkingStartData(CamelModel):
    run_id: str
    message_id: str


class ThinkingDeltaData(CamelModel):
    run_id: str
    message_id: str
    delta: str


class ThinkingEndData(CamelModel):
    run_id: str
    message_id: str


class ToolCallStartData(CamelModel):
    run_id: str
    tool_call_id: str
    name: str
    args: dict[str, Any]  # 必填（与 TS 侧对齐：工具调用总是携带 args，可为空对象）


class ToolCallEndData(CamelModel):
    run_id: str
    tool_call_id: str
    status: ToolCallStatus
    result: Any | None = None
    error: ErrorPayload | None = None


class EmotionData(CamelModel):
    run_id: str | None = None
    emotion: Emotion
    intensity: float = Field(ge=0.0, le=1.0)


class StateChangeData(CamelModel):
    state: CharacterState


# ---------------------------------------------------------------------------
# 事件类型常量与负载注册表（与 TS 侧 EVENT_TYPES / COMMAND_TYPES 一致）
# ---------------------------------------------------------------------------
COMMAND_TYPES = {
    "hello": "hello",
    "ping": "ping",
    "chat.send": "chat.send",
    "chat.cancel": "chat.cancel",
    "chat.interrupt": "chat.interrupt",
}

EVENT_TYPES = {
    "hello_ack": "hello_ack",
    "hello_error": "hello_error",
    "pong": "pong",
    "run.started": "run.started",
    "run.finished": "run.finished",
    "run.error": "run.error",
    "text.start": "text.start",
    "text.delta": "text.delta",
    "text.end": "text.end",
    "thinking.start": "thinking.start",
    "thinking.delta": "thinking.delta",
    "thinking.end": "thinking.end",
    "tool.call.start": "tool.call.start",
    "tool.call.end": "tool.call.end",
    "emotion": "emotion",
    "state.change": "state.change",
}

COMMAND_DATA_MODELS: dict[str, type[CamelModel]] = {
    "hello": HelloData,
    "ping": PingData,
    "chat.send": ChatSendData,
    "chat.cancel": ChatCancelData,
    "chat.interrupt": ChatInterruptData,
}

EVENT_DATA_MODELS: dict[str, type[CamelModel]] = {
    "hello_ack": HelloAckData,
    "hello_error": HelloErrorData,
    "pong": PongData,
    "run.started": RunStartedData,
    "run.finished": RunFinishedData,
    "run.error": RunErrorData,
    "text.start": TextStartData,
    "text.delta": TextDeltaData,
    "text.end": TextEndData,
    "thinking.start": ThinkingStartData,
    "thinking.delta": ThinkingDeltaData,
    "thinking.end": ThinkingEndData,
    "tool.call.start": ToolCallStartData,
    "tool.call.end": ToolCallEndData,
    "emotion": EmotionData,
    "state.change": StateChangeData,
}
