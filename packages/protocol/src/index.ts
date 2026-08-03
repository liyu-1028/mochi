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

/** 标准化错误码（规范文档 §7） */
export const ERROR_CODES = {
  VersionMismatch: "ERR_VERSION_MISMATCH",
  ModelAuth: "ERR_MODEL_AUTH",
  ModelUnavailable: "ERR_MODEL_UNAVAILABLE",
  ModelRateLimit: "ERR_MODEL_RATE_LIMIT",
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
}

export interface TextDeltaData {
  runId: string;
  messageId: string;
  delta: string;
}

export interface TextEndData {
  runId: string;
  messageId: string;
  fullText: string;
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
  | Envelope<ChatInterruptData>;

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
  | Envelope<StateChangeData>;
