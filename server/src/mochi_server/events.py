"""Mochi Agent 事件协议 v0.1 —— Python 侧镜像定义。

规范文档：docs/protocol/agent-events-v0.1.md
前端事实源：packages/protocol/src/index.ts

⚠️ 本文件必须与 TS 定义保持逐字段一致。0.x 阶段人工同步；
一致性黄金样例：packages/protocol/testdata/turn-with-tool-call.jsonl
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

PROTOCOL_VERSION = "0.1"
SERVER_NAME = "mochi-server"


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
    NETWORK = "ERR_NETWORK"
    CONTEXT_OVERFLOW = "ERR_CONTEXT_OVERFLOW"
    TOOL_DENIED = "ERR_TOOL_DENIED"
    TOOL_FAILED = "ERR_TOOL_FAILED"
    CANCELLED = "ERR_CANCELLED"
    INTERNAL = "ERR_INTERNAL"


RunFinishReason = Literal["complete", "cancelled", "interrupted", "error"]
ToolCallStatus = Literal["success", "error", "denied"]


# ---------------------------------------------------------------------------
# 信封与负载
# ---------------------------------------------------------------------------
class Envelope(BaseModel):
    """通用信封：所有 WebSocket JSON 帧共享的外层结构。

    序列化使用 camelCase（与 TS 侧一致）：pydantic v2 通过
    model_config / alias 生成时统一转换。
    """

    v: str = PROTOCOL_VERSION
    type: str
    id: str = Field(default_factory=lambda: str(uuid4()))
    ts: int  # 毫秒级 Unix 时间戳，发送时填充
    data: dict[str, Any] = Field(default_factory=dict)


class ErrorPayload(BaseModel):
    code: str
    message: str  # 用户可读文案，禁止裸露堆栈（功能清单 6.7）
    retryable: bool = False
    hint: str | None = None


# --- 客户端 → 服务端命令负载 ---
class HelloData(BaseModel):
    versions: list[str]
    client: dict[str, str]


class ChatSendData(BaseModel):
    run_id: str = Field(serialization_alias="runId")
    session_id: str = Field(serialization_alias="sessionId")
    text: str
    attachments: list[dict[str, str]] | None = None


class ChatCancelData(BaseModel):
    run_id: str = Field(serialization_alias="runId")


class ChatInterruptData(BaseModel):
    run_id: str = Field(serialization_alias="runId")


# --- 服务端 → 客户端事件负载 ---
class HelloAckData(BaseModel):
    version: str
    server: dict[str, str]


class RunStartedData(BaseModel):
    run_id: str = Field(serialization_alias="runId")
    session_id: str = Field(serialization_alias="sessionId")


class RunFinishedData(BaseModel):
    run_id: str = Field(serialization_alias="runId")
    reason: RunFinishReason
    usage: dict[str, int] | None = None


class RunErrorData(BaseModel):
    run_id: str = Field(serialization_alias="runId")
    error: ErrorPayload


class TextStartData(BaseModel):
    run_id: str = Field(serialization_alias="runId")
    message_id: str = Field(serialization_alias="messageId")
    role: Literal["assistant"] = "assistant"


class TextDeltaData(BaseModel):
    run_id: str = Field(serialization_alias="runId")
    message_id: str = Field(serialization_alias="messageId")
    delta: str


class TextEndData(BaseModel):
    run_id: str = Field(serialization_alias="runId")
    message_id: str = Field(serialization_alias="messageId")
    full_text: str = Field(serialization_alias="fullText")


class ThinkingStartData(BaseModel):
    run_id: str = Field(serialization_alias="runId")
    message_id: str = Field(serialization_alias="messageId")


class ThinkingDeltaData(BaseModel):
    run_id: str = Field(serialization_alias="runId")
    message_id: str = Field(serialization_alias="messageId")
    delta: str


class ThinkingEndData(BaseModel):
    run_id: str = Field(serialization_alias="runId")
    message_id: str = Field(serialization_alias="messageId")


class ToolCallStartData(BaseModel):
    run_id: str = Field(serialization_alias="runId")
    tool_call_id: str = Field(serialization_alias="toolCallId")
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolCallEndData(BaseModel):
    run_id: str = Field(serialization_alias="runId")
    tool_call_id: str = Field(serialization_alias="toolCallId")
    status: ToolCallStatus
    result: Any | None = None
    error: ErrorPayload | None = None


class EmotionData(BaseModel):
    run_id: str | None = Field(default=None, serialization_alias="runId")
    emotion: Emotion
    intensity: float = Field(ge=0.0, le=1.0)


class StateChangeData(BaseModel):
    state: CharacterState


# ---------------------------------------------------------------------------
# 事件类型常量（与 TS 侧 EVENT_TYPES / COMMAND_TYPES 一致）
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
