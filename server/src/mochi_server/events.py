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


# ---------------------------------------------------------------------------
# 语义动作注册表（M-A，角色行为运行时）
# ---------------------------------------------------------------------------
# 白名单词表：skin manifest `actions` 字段与后续 character.cue 事件共用的
# 动作 id 集合。皮肤只需实现子集，未实现的沿 fallback 链降级到 idle_neutral。
# 双端镜像：packages/protocol/src/index.ts；共享夹具：testdata/semantic-actions.json。
# 语义动作 id 集合（TS 侧 `SemanticActionId`）
SEMANTIC_ACTIONS = (
    "idle_neutral",
    "look_around",
    "think",
    "listen",
    "wave",
    "nod",
    "shake_head",
    "celebrate",
    "comfort",
    "surprised",
    "stretch",
    "doze",
    "wink",  # 舞台指示解析（M-F）新增：参数包络实现，无需模型自带 motion
    "pout",  # G1（L1 包络扩容）：嘟嘴——参数包络实现
    "laugh",  # G1：大笑——参数包络实现
    "shy_shake",  # G1：扭捏（左右小摇+脸红）——参数包络实现
    "alert",  # G1：警觉（猛抬头+睁眼）——参数包络实现
)

# 动作展示名（G2）：提示词能力注入与日志的统一中文名；与词表同键集，
# 双端镜像 packages/protocol/src/index.ts；golden：testdata/semantic-actions.json
ACTION_LABELS: dict[str, str] = {
    "idle_neutral": "平静",
    "look_around": "东张西望",
    "think": "沉思",
    "listen": "竖耳听",
    "wave": "挥手",
    "nod": "点头",
    "shake_head": "摇头",
    "celebrate": "欢呼鼓掌",
    "comfort": "拍拍安慰",
    "surprised": "吓一跳",
    "stretch": "伸懒腰",
    "doze": "打哈欠犯困",
    "wink": "眨眨眼",
    "pout": "嘟嘴",
    "laugh": "大笑",
    "shy_shake": "扭捏",
    "alert": "警觉精神",
}

# 动作通道（调研报告 §8.3）；M-A 仅 face/body/effect 可执行，其余预留
ACTION_CHANNELS = ("face", "body", "locomotion", "voice", "effect")


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
# 陪伴信号（M-D，调研报告 §8.2 决策点 3）
# ---------------------------------------------------------------------------
# 信号只描述事实，不直接命令角色「说某句话」；是否开口由服务端注意力引擎
# 经打扰门控（§8.6）决定。信号源在两端（前端：idle/触摸；服务端：工具事件），
# 统一汇聚到服务端。

#: 信号类别（TS 侧 SIGNAL_KINDS）；intent_response = ask 快速操作的回传
SIGNAL_KINDS = (
    "touch",
    "drag",
    "message",
    "tool_started",
    "tool_finished",
    "tool_failed",
    "tool_needs_user",
    "idle",
    "focus_session",
    "commitment_due",
    "context_summary",
    "intent_response",
)

#: 信号显著性 0~3（弱/普通/强，调研报告 §4.2）
SIGNAL_SALIENCE = (0, 1, 2, 3)

#: 主动意图动作（§4.3 两阶段决策；silent/action_intent 不出事件）
INTENT_ACTIONS = ("speak", "ask")

#: ask_intent 的快速操作按钮（§8.6：尽量提供「稍后」「不用提醒」）
INTENT_QUICK_REPLIES = ("later", "dismiss")

#: 快速操作回传决定（经 companion.signal kind=intent_response）
INTENT_DECISIONS = ("later", "dismiss", "now")

#: 回合/消息来源（§8 决策点 4，已定）：主动消息复用 text 事件族 + source 字段
MESSAGE_SOURCES = ("user", "proactive")


class CompanionSignalData(CamelModel):
    """companion.signal 命令负载：一次陪伴信号上报。"""

    signal_id: str  # 客户端生成的去重 id
    kind: str  # SIGNAL_KINDS 之一
    occurred_at: int  # 信号发生时刻（epoch ms）
    salience: int = Field(ge=0, le=3)
    dedupe_key: str | None = None  # 同主题合并/冷却键（如 tool:bash）
    not_before: int | None = None  # 最早允许处理时刻（epoch ms）
    expires_at: int | None = None  # 过期时刻；过期信号无声丢弃
    payload: dict[str, Any] = Field(default_factory=dict)  # kind 相关事实载荷


class CompanionIntentData(CamelModel):
    """companion.intent 事件负载：通过门控的主动意图（speak/ask）。"""

    intent_id: str
    action: str  # INTENT_ACTIONS 之一
    kind: str  # 触发信号 kind
    quick_replies: list[str] = Field(default_factory=list)  # INTENT_QUICK_REPLIES 子集
    expires_at: int | None = None  # 无声过期时刻：过期后前端移除提示，不残留 UI


class ToolConfirmData(CamelModel):
    """危险工具确认（M1-S4，功能清单 6.5；协议 §4）。

    decision：allow 放行本次执行；deny 拒绝（→ tool.call.end status=denied）。
    remember=true 表示「总是允许」——工具名入 [tools] 白名单（任务 7 语义，
    协议只携带不解释）。
    """

    run_id: str
    tool_call_id: str
    decision: Literal["allow", "deny"]
    remember: bool = False


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
    # 回合来源（M-D）：proactive = 主动发起（无用户输入）；缺省按 user
    source: str = "user"
    intent_id: str | None = None  # proactive 时关联的意图 id（companion.intent 同名）


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
    source: str = "user"  # 消息来源（M-D §8 决策点 4）：缺省按 user


class TextDeltaData(CamelModel):
    run_id: str
    message_id: str
    delta: str
    source: str = "user"  # 与 text.start 一致（M-D）；缺省按 user


class TextEndData(CamelModel):
    run_id: str
    message_id: str
    full_text: str
    source: str = "user"  # 与 text.start 一致（M-D）；缺省按 user


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
    # 危险工具须用户确认（M1-S4，6.5；协议 §5.5）。缺省 False：safe 工具与
    # 旧服务端帧不受影响（0.x additive，§9.1）
    requires_confirmation: bool = False


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
# 表演节拍 cue（M-C，调研报告 §8.3）
# ---------------------------------------------------------------------------
# TS 侧：CUE_SOURCES / CUE_SYNC / CUE_INTERRUPT_POLICIES / CharacterCueData；
# 夹具：packages/protocol/testdata/character-cue.json。控制信息不进气泡、
# 不进 TTS；模型只能选择 agentSelectable 动作 id（服务端白名单强校验）。

CueSource = Literal["reflex", "reply", "system", "proactive"]
CueSync = Literal["immediate", "speech_start", "sentence_boundary", "speech_end"]
CueInterruptPolicy = Literal["replace", "queue", "ignore"]

#: 枚举值显式登记（Literal 无法反射；cue 提取器校验与夹具测试共用，顺序敏感）
CUE_SOURCE_VALUES = ("reflex", "reply", "system", "proactive")
CUE_SYNC_VALUES = ("immediate", "speech_start", "sentence_boundary", "speech_end")
CUE_INTERRUPT_POLICY_VALUES = ("replace", "queue", "ignore")


class CueFaceChannel(CamelModel):
    """face 通道：emotion ∈ EMOTIONS（服务端校验）。"""

    emotion: Emotion
    intensity: float | None = Field(default=None, ge=0.0, le=1.0)


class CueBodyChannel(CamelModel):
    """body 通道：actionId ∈ SEMANTIC_ACTIONS（白名单强校验）。"""

    action_id: str
    variant: str | None = None


class CueLocomotionChannel(CamelModel):
    """M-C 预留：服务端不产出，前端忽略。"""

    action_id: str


class CueVoiceChannel(CamelModel):
    """M-C 预留：服务端不产出，前端忽略。"""

    tone: str | None = None
    rate: float | None = None


class CueEffectChannel(CamelModel):
    """M-C 预留：服务端不产出，前端忽略。"""

    id: str


class CueChannels(CamelModel):
    face: CueFaceChannel | None = None
    body: CueBodyChannel | None = None
    locomotion: CueLocomotionChannel | None = None
    voice: CueVoiceChannel | None = None
    effect: CueEffectChannel | None = None


class CharacterCueData(CamelModel):
    """character.cue 负载：一次回答中的单个表演节拍。"""

    cue_id: str
    run_id: str | None = None
    message_id: str | None = None
    source: CueSource
    channels: CueChannels
    sync: CueSync
    sentence_index: int | None = None  # 1-based；sentence_boundary 时必填
    priority: int = Field(ge=0, le=100)  # reply 来源服务端定值，模型不可指定
    interrupt_policy: CueInterruptPolicy
    ttl_ms: int = Field(ge=0)  # 从信封 ts 起算，过期不补演


# ---------------------------------------------------------------------------
# 事件类型常量与负载注册表（与 TS 侧 EVENT_TYPES / COMMAND_TYPES 一致）
# ---------------------------------------------------------------------------
COMMAND_TYPES = {
    "hello": "hello",
    "ping": "ping",
    "chat.send": "chat.send",
    "chat.cancel": "chat.cancel",
    "chat.interrupt": "chat.interrupt",
    "tool.confirm": "tool.confirm",
    "companion.signal": "companion.signal",
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
    "character.cue": "character.cue",
    "companion.intent": "companion.intent",
}

COMMAND_DATA_MODELS: dict[str, type[CamelModel]] = {
    "hello": HelloData,
    "ping": PingData,
    "chat.send": ChatSendData,
    "chat.cancel": ChatCancelData,
    "chat.interrupt": ChatInterruptData,
    "tool.confirm": ToolConfirmData,
    "companion.signal": CompanionSignalData,
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
    "character.cue": CharacterCueData,
    "companion.intent": CompanionIntentData,
}
