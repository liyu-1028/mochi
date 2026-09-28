/**
 * Mochi Agent 事件协议 v0.1
 *
 * 规范文档：docs/protocol/agent-events-v0.1.md
 * 本包是前端侧的唯一事实源；Python sidecar 侧的镜像定义在
 * server/src/mochi_server/events.py，两者必须保持一致（0.x 阶段人工同步，
 * 一致性测试见 docs/specs/monorepo-structure.md §4）。
 */

export const PROTOCOL_VERSION = "0.1";

// ---------------------------------------------------------------------------
// 通用信封（Envelope）
// ---------------------------------------------------------------------------

/** 毫秒级 Unix 时间戳 */
export type Timestamp = number;

export interface Envelope<TData> {
  /** 协议版本，固定为 PROTOCOL_VERSION */
  v: string;
  /** 命令/事件类型 */
  type: string;
  /** 本条消息的唯一 ID（UUID v4） */
  id: string;
  /** 发送方时间戳（ms） */
  ts: Timestamp;
  /** 负载 */
  data: TData;
}

// ---------------------------------------------------------------------------
// 客户端 → 服务端：命令
// ---------------------------------------------------------------------------

export const COMMAND_TYPES = {
  Hello: "hello",
  Ping: "ping",
  ChatSend: "chat.send",
  ChatCancel: "chat.cancel",
  ChatInterrupt: "chat.interrupt",
  ToolConfirm: "tool.confirm",
  CompanionSignal: "companion.signal",
} as const;

export type CommandType = (typeof COMMAND_TYPES)[keyof typeof COMMAND_TYPES];

/** 客户端标识（hello 命令） */
export interface ClientInfo {
  name: string;
  version: string;
}

/** 服务端标识（hello_ack 事件） */
export interface ServerInfo {
  name: string;
  version: string;
}

/** 握手：声明客户端支持的协议版本（按偏好降序） */
export interface HelloData {
  versions: string[];
  client: ClientInfo;
}

export interface PingData {
  /** 原样回传，用于 RTT 测量 */
  token?: string;
}

/** 发起一次对话回合（run 由客户端生成 UUID，便于乐观 UI 与取消） */
export interface ChatSendData {
  runId: string;
  sessionId: string;
  text: string;
  attachments?: Attachment[];
}

export interface Attachment {
  kind: "image" | "file";
  /** 本地绝对路径（桌面端）；M0 仅支持本地文件引用 */
  path: string;
  name: string;
}

/** 取消生成：丢弃当前 run 的后续输出 */
export interface ChatCancelData {
  runId: string;
}

/** 打断播报：停止 TTS 播放/输出展示，但已生成内容保留（语音 barge-in 场景） */
export interface ChatInterruptData {
  runId: string;
}

// ---------------------------------------------------------------------------
// 陪伴信号（M-D，调研报告 §8.2 决策点 3）
// ---------------------------------------------------------------------------
// 信号只描述事实，不直接命令角色「说某句话」；是否开口由服务端注意力引擎
// 经打扰门控（§8.6）决定。信号源在两端（前端：idle/触摸；服务端：工具事件），
// 统一汇聚到服务端。

export const SIGNAL_KINDS = [
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
] as const;
export type SignalKind = (typeof SIGNAL_KINDS)[number];

/** 信号显著性 0~3（弱/普通/强，调研报告 §4.2）；引擎据此设置等待与合并策略 */
export const SIGNAL_SALIENCE = [0, 1, 2, 3] as const;
export type SignalSalience = (typeof SIGNAL_SALIENCE)[number];

/** 主动意图动作（§4.3 两阶段决策：注意力层只产出这四种，前两种不出事件） */
export const INTENT_ACTIONS = ["speak", "ask"] as const;
export type IntentAction = (typeof INTENT_ACTIONS)[number];

/** ask_intent 的快速操作按钮（§8.6：尽量提供「稍后」「不用提醒」） */
export const INTENT_QUICK_REPLIES = ["later", "dismiss"] as const;
export type IntentQuickReply = (typeof INTENT_QUICK_REPLIES)[number];

/** 快速操作的回传决定（经 companion.signal kind=intent_response） */
export const INTENT_DECISIONS = ["later", "dismiss", "now"] as const;
export type IntentDecision = (typeof INTENT_DECISIONS)[number];

/** 回合/消息来源（§8 决策点 4，已定）：主动消息复用 text 事件族 + source 字段 */
export const MESSAGE_SOURCES = ["user", "proactive"] as const;
export type MessageSource = (typeof MESSAGE_SOURCES)[number];

/** companion.signal 命令负载：一次陪伴信号上报 */
export interface CompanionSignalData {
  /** 客户端生成的去重 id */
  signalId: string;
  kind: SignalKind;
  /** 信号发生时刻（epoch ms） */
  occurredAt: number;
  salience: SignalSalience;
  /** 同主题合并/冷却键（如 tool:bash） */
  dedupeKey?: string;
  /** 最早允许处理时刻（epoch ms）；引擎不早于此触发 */
  notBefore?: number;
  /** 过期时刻（epoch ms）；过期信号无声丢弃 */
  expiresAt?: number;
  /** kind 相关事实载荷（如 tool 失败次数、连续活跃时长） */
  payload: Record<string, unknown>;
}

/** companion.intent 事件负载：通过门控的主动意图（speak/ask） */
export interface CompanionIntentData {
  intentId: string;
  action: IntentAction;
  /** 触发信号 kind */
  kind: SignalKind;
  /** ask 的快速操作按钮；空数组 = 无快速操作 */
  quickReplies: IntentQuickReply[];
  /** 无声过期时刻（epoch ms）：过期后前端移除提示，不残留 UI */
  expiresAt?: number;
}

// ---------------------------------------------------------------------------
// 服务端 → 客户端：事件
// ---------------------------------------------------------------------------

export const EVENT_TYPES = {
  HelloAck: "hello_ack",
  HelloError: "hello_error",
  Pong: "pong",
  RunStarted: "run.started",
  RunFinished: "run.finished",
  RunError: "run.error",
  TextStart: "text.start",
  TextDelta: "text.delta",
  TextEnd: "text.end",
  ThinkingStart: "thinking.start",
  ThinkingDelta: "thinking.delta",
  ThinkingEnd: "thinking.end",
  ToolCallStart: "tool.call.start",
  ToolCallEnd: "tool.call.end",
  Emotion: "emotion",
  StateChange: "state.change",
  CharacterCue: "character.cue",
  CompanionIntent: "companion.intent",
} as const;

export type EventType = (typeof EVENT_TYPES)[keyof typeof EVENT_TYPES];

/** Mochi 扩展：角色情绪（功能清单 2.5，≥5 种） */
export const EMOTIONS = [
  "neutral",
  "happy",
  "sad",
  "confused",
  "surprised",
  "embarrassed",
  "angry",
] as const;
export type Emotion = (typeof EMOTIONS)[number];

/** Mochi 扩展：角色动画状态机状态（功能清单 2.2，6 状态） */
export const CHARACTER_STATES = [
  "idle",
  "talking",
  "thinking",
  "working",
  "error",
  "sleeping",
] as const;
export type CharacterState = (typeof CHARACTER_STATES)[number];

// ---------------------------------------------------------------------------
// 语义动作注册表（M-A，角色行为运行时）
// ---------------------------------------------------------------------------
// 白名单词表：skin manifest `actions` 字段与后续 character.cue 事件共用的
// 动作 id 集合。皮肤只需实现子集，未实现的沿 fallback 链降级到 idle_neutral。
// 双端镜像：server/src/mochi_server/events.py；共享夹具：testdata/semantic-actions.json。

export const SEMANTIC_ACTIONS = [
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
  // wink（眨眼）：舞台指示解析（M-F）新增——参数包络实现，无需模型自带 motion
  "wink",
  // G1（L1 包络扩容）：嘟嘴/大笑/扭捏/警觉——均参数包络实现，任何 Cubism 模型可演
  "pout",
  "laugh",
  "shy_shake",
  "alert",
] as const;
export type SemanticActionId = (typeof SEMANTIC_ACTIONS)[number];

/** 动作通道（调研报告 §8.3）；M-A 仅 face/body/effect 可执行，其余预留 */
export const ACTION_CHANNELS = ["face", "body", "locomotion", "voice", "effect"] as const;
export type ActionChannel = (typeof ACTION_CHANNELS)[number];

/** 标准化错误码（规范文档 §7） */
export const ERROR_CODES = {
  VersionMismatch: "ERR_VERSION_MISMATCH",
  ModelAuth: "ERR_MODEL_AUTH",
  ModelUnavailable: "ERR_MODEL_UNAVAILABLE",
  ModelRateLimit: "ERR_MODEL_RATE_LIMIT",
  ModelQuota: "ERR_MODEL_QUOTA",
  Network: "ERR_NETWORK",
  ContextOverflow: "ERR_CONTEXT_OVERFLOW",
  ToolDenied: "ERR_TOOL_DENIED",
  ToolFailed: "ERR_TOOL_FAILED",
  Cancelled: "ERR_CANCELLED",
  Internal: "ERR_INTERNAL",
} as const;
export type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];

export const RUN_FINISH_REASONS = ["complete", "cancelled", "interrupted", "error"] as const;
export type RunFinishReason = (typeof RUN_FINISH_REASONS)[number];

export const TOOL_CALL_STATUSES = ["success", "error", "denied"] as const;
export type ToolCallStatus = (typeof TOOL_CALL_STATUSES)[number];

// ---------------------------------------------------------------------------
// 表演节拍 cue（M-C，调研报告 §8.3）
// ---------------------------------------------------------------------------
// character.cue 事件的枚举与负载。控制信息不进气泡、不进 TTS；
// 模型只能选择 agentSelectable 动作 id（服务端白名单强校验，越权丢弃）。
// 双端镜像：server/src/mochi_server/events.py；夹具：testdata/character-cue.json。

/** cue 来源：reflex=本地反射（M-B 前端内产生，不经协议）；reply=回复节拍；
 *  system=系统级（工具/错误等）；proactive=主动开口（M-D 预留） */
export const CUE_SOURCES = ["reflex", "reply", "system", "proactive"] as const;
export type CueSource = (typeof CUE_SOURCES)[number];

/** 节拍对齐点：immediate=立即；speech_start=开始播报；
 *  sentence_boundary=第 sentenceIndex 句开始播报；speech_end=播报结束 */
export const CUE_SYNC = ["immediate", "speech_start", "sentence_boundary", "speech_end"] as const;
export type CueSync = (typeof CUE_SYNC)[number];

/** 同通道新 cue 到达时对当前动作的处理（语义与 director interruptPolicy 一致） */
export const CUE_INTERRUPT_POLICIES = ["replace", "queue", "ignore"] as const;
export type CueInterruptPolicy = (typeof CUE_INTERRUPT_POLICIES)[number];

/** face 通道：emotion ∈ EMOTIONS 词表（服务端校验） */
export interface CueFaceChannel {
  emotion: Emotion;
  /** 0~1，缺省 0.75 */
  intensity?: number;
}

/** body 通道：actionId ∈ SEMANTic_ACTIONS（服务端白名单强校验） */
export interface CueBodyChannel {
  actionId: SemanticActionId | string;
  /** 预留：同动作的变体 */
  variant?: string;
}

/** 以下通道 M-C 预留（服务端不产出，前端忽略）；字段形态按调研报告 §8.3 冻结 */
export interface CueLocomotionChannel {
  actionId: string;
}
export interface CueVoiceChannel {
  tone?: string;
  /** 语速倍率，1.0 = 正常 */
  rate?: number;
}
export interface CueEffectChannel {
  id: string;
}

export interface CueChannels {
  face?: CueFaceChannel;
  body?: CueBodyChannel;
  locomotion?: CueLocomotionChannel;
  voice?: CueVoiceChannel;
  effect?: CueEffectChannel;
}

/** character.cue 负载：一次回答中的单个表演节拍 */
export interface CharacterCueData {
  cueId: string;
  runId?: string;
  messageId?: string;
  source: CueSource;
  channels: CueChannels;
  sync: CueSync;
  /** 1-based；sync=sentence_boundary 时必填，表示「该句开始播报时执行」 */
  sentenceIndex?: number;
  /** 0~100；reply 来源服务端定值，模型不可指定 */
  priority: number;
  interruptPolicy: CueInterruptPolicy;
  /** 从信封 ts 起算的存活窗口；过期不补演 */
  ttlMs: number;
}

// --- 事件负载 ---

export interface HelloAckData {
  /** 协商选定的协议版本 */
  version: string;
  server: ServerInfo;
}

export interface HelloErrorData {
  error: ErrorPayload;
}

export interface PongData {
  token?: string;
}

export interface RunStartedData {
  runId: string;
  sessionId: string;
  /** 回合来源（M-D）：proactive = 主动发起（无用户输入）；缺省按 user */
  source?: MessageSource;
  /** proactive 时关联的意图 id（companion.intent 同名） */
  intentId?: string;
}

/** run.finished 的 token 用量（可选） */
export interface UsageInfo {
  promptTokens?: number;
  completionTokens?: number;
}

export interface RunFinishedData {
  runId: string;
  reason: RunFinishReason;
  usage?: UsageInfo;
}

export interface RunErrorData {
  runId: string;
  error: ErrorPayload;
}

export interface ErrorPayload {
  code: ErrorCode | string;
  /** 用户可读文案（规范：禁止裸露堆栈，功能清单 6.7） */
  message: string;
  retryable: boolean;
  /** 可选的排查建议 */
  hint?: string;
}

export interface TextStartData {
  runId: string;
  messageId: string;
  role: "assistant";
  /** 消息来源（M-D §8 决策点 4）：缺省按 user */
  source?: MessageSource;
}

export interface TextDeltaData {
  runId: string;
  messageId: string;
  delta: string;
  /** 与 text.start 一致（M-D）；缺省按 user */
  source?: MessageSource;
}

export interface TextEndData {
  runId: string;
  messageId: string;
  fullText: string;
  /** 与 text.start 一致（M-D）；缺省按 user */
  source?: MessageSource;
}

/** Mochi 扩展事件：模型思考过程，驱动角色「思考」动画 */
export interface ThinkingStartData {
  runId: string;
  messageId: string;
}

export interface ThinkingDeltaData {
  runId: string;
  messageId: string;
  delta: string;
}

export interface ThinkingEndData {
  runId: string;
  messageId: string;
}

export interface ToolCallStartData {
  runId: string;
  toolCallId: string;
  name: string;
  args: Record<string, unknown>;
  /** 危险工具须用户确认（6.5）。缺省 false：safe 工具与旧服务端帧不受影响 */
  requiresConfirmation?: boolean;
}

/** 危险工具确认（M1-S4，6.5；协议 §4）。remember=true 表示「总是允许」 */
export interface ToolConfirmData {
  runId: string;
  toolCallId: string;
  decision: "allow" | "deny";
  remember?: boolean;
}

export interface ToolCallEndData {
  runId: string;
  toolCallId: string;
  status: ToolCallStatus;
  result?: unknown;
  error?: ErrorPayload;
}

export interface EmotionData {
  runId?: string;
  emotion: Emotion;
  /** 0~1，表情强度/持续时间权重 */
  intensity: number;
}

export interface StateChangeData {
  state: CharacterState;
}

// ---------------------------------------------------------------------------
// 判别联合（前端 switch/消费用）
// ---------------------------------------------------------------------------

export type ClientCommand =
  | Envelope<HelloData>
  | Envelope<PingData>
  | Envelope<ChatSendData>
  | Envelope<ChatCancelData>
  | Envelope<ChatInterruptData>
  | Envelope<ToolConfirmData>
  | Envelope<CompanionSignalData>;

/** 构建客户端命令帧（统一填充 v/id/ts，消费方无需手写信封）。 */
export function createCommand<T>(type: CommandType, data: T): Envelope<T> {
  return {
    v: PROTOCOL_VERSION,
    type,
    id: crypto.randomUUID(),
    ts: Date.now(),
    data,
  };
}

export type ServerEvent =
  | Envelope<HelloAckData>
  | Envelope<HelloErrorData>
  | Envelope<PongData>
  | Envelope<RunStartedData>
  | Envelope<RunFinishedData>
  | Envelope<RunErrorData>
  | Envelope<TextStartData>
  | Envelope<TextDeltaData>
  | Envelope<TextEndData>
  | Envelope<ThinkingStartData>
  | Envelope<ThinkingDeltaData>
  | Envelope<ThinkingEndData>
  | Envelope<ToolCallStartData>
  | Envelope<ToolCallEndData>
  | Envelope<EmotionData>
  | Envelope<StateChangeData>
  | Envelope<CharacterCueData>
  | Envelope<CompanionIntentData>;
