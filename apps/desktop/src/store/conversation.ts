/**
 * conversation store —— 事件协议 → UI 状态 的唯一归约器。
 *
 * 纯状态逻辑（不持有 WebSocket 实例），便于 vitest 直测。
 * 未知事件类型一律忽略（协议 §1.3 前向兼容）。
 */
import { EVENT_TYPES, type CharacterState, type Emotion, type ServerEvent } from "@mochi/protocol";
import { create } from "zustand";
import type { ConnectionStatus } from "../ws/WebSocketClient";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  streaming: boolean;
  /** 历史回显消息（hydrateHistory 注入）：不以气泡形式在主界面闪现，
      仅在聊天回忆面板回顾（测试报告 2026-08-05 Bug 3）。 */
  fromHistory?: boolean;
}

/** 内存中保留的消息上限（M1-S1）：超出裁掉最旧，历史事实源在 sidecar SQLite。 */
export const MAX_IN_MEMORY_MESSAGES = 40;

/** 纯函数：追加一条消息并裁剪到最近 max 条（保持时间正序）。 */
export function appendCapped(
  messages: ChatMessage[],
  next: ChatMessage,
  max: number,
): ChatMessage[] {
  const appended = [...messages, next];
  return appended.length > max ? appended.slice(appended.length - max) : appended;
}

/** 纯函数：run 终态兜底收口——把仍处于 streaming 的消息统一置为完成。
    异常路径（超时/限流/Key 失效）后端会跳过 text.end 直接发 run.error /
    run.finished，若不清理则气泡光标 ▍ 与口型状态永久残留
    （测试报告 2026-08-05：streaming 状态未闭合）。 */
export function finalizeStreamingMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.some((m) => m.streaming)
    ? messages.map((m) => (m.streaming ? { ...m, streaming: false } : m))
    : messages;
}

/** 纯函数：把后端历史消息映射为 UI 消息（用于重启后回显）。
    全部打 fromHistory 标记：气泡区据此过滤，避免历史批量闪现。 */
export function historyToMessages(
  history: ReadonlyArray<{ role: "user" | "assistant"; content: string; ts: number }>,
): ChatMessage[] {
  return history.map((h, i) => ({
    id: `h-${h.ts}-${i}`,
    role: h.role,
    text: h.content,
    streaming: false,
    fromHistory: true,
  }));
}

export interface ConversationState {
  status: ConnectionStatus;
  characterState: CharacterState;
  emotion: Emotion | null;
  messages: ChatMessage[];
  /** 当前活跃回合；为 null 时允许发起新对话 */
  activeRunId: string | null;
  /** 错误/提示横幅文案（run.error、hello_error） */
  notice: string | null;
  /** 口型驱动信号（M0-S3，功能清单 2.3）：最近 delta 时间戳/内容/说话区间 */
  lastTextDeltaAt: number;
  lastTextDelta: string;
  isSpeaking: boolean;

  setStatus: (status: ConnectionStatus) => void;
  addUserMessage: (text: string) => void;
  applyEvent: (event: ServerEvent) => void;
  clearNotice: () => void;
  /** 重启后从 sidecar 拉取历史回显（仅当当前无消息时生效，避免重连重复）。 */
  hydrateHistory: (messages: ChatMessage[]) => void;
  /** 清空主界面内存消息：回忆面板删除活跃会话后调用，保证前端内存状态
      与 sidecar 持久化一致（测试报告 2026-08-06 问题 2：删除后状态脱节）。 */
  resetMessages: () => void;
}

export const useConversation = create<ConversationState>()((set, get) => ({
  status: "disconnected",
  characterState: "idle",
  emotion: null,
  messages: [],
  activeRunId: null,
  notice: null,
  lastTextDeltaAt: 0,
  lastTextDelta: "",
  isSpeaking: false,

  setStatus: (status) => set({ status }),

  addUserMessage: (text) =>
    set((s) => ({
      messages: appendCapped(
        s.messages,
        { id: `u-${crypto.randomUUID()}`, role: "user", text, streaming: false },
        MAX_IN_MEMORY_MESSAGES,
      ),
    })),

  clearNotice: () => set({ notice: null }),

  hydrateHistory: (incoming) =>
    set((s) => {
      // 已有消息（重连/本轮已对话）则不覆盖；仅在空白时回显历史
      if (s.messages.length > 0) return {};
      const capped =
        incoming.length > MAX_IN_MEMORY_MESSAGES
          ? incoming.slice(incoming.length - MAX_IN_MEMORY_MESSAGES)
          : incoming;
      return { messages: capped };
    }),

  resetMessages: () => set({ messages: [], isSpeaking: false }),

  applyEvent: (event) => {
    const data = event.data as Record<string, unknown>;

    switch (event.type) {
      case EVENT_TYPES.RunStarted:
        set({ activeRunId: data.runId as string, notice: null });
        break;

      case EVENT_TYPES.RunFinished:
        // 终态兜底收口：异常路径可能缺失 text.end，统一归零残留的 streaming
        // 与口型信号，杜绝"生成中"假象（测试报告 2026-08-05）
        set((s) => ({
          activeRunId: null,
          messages: finalizeStreamingMessages(s.messages),
          isSpeaking: false,
        }));
        break;

      case EVENT_TYPES.RunError: {
        const error = data.error as { message?: string; hint?: string } | undefined;
        // hint 优先：适配层针对 Key/网络/限流的引导文案（功能清单 6.7）；
        // 同样收口 streaming——错误常发生在 text.start 之后、text.end 之前
        set((s) => ({
          notice: error?.hint ?? error?.message ?? "出了点问题，请重试",
          messages: finalizeStreamingMessages(s.messages),
          isSpeaking: false,
        }));
        break;
      }

      case EVENT_TYPES.HelloError: {
        const error = data.error as { message?: string; hint?: string } | undefined;
        set({ notice: error?.hint ?? error?.message ?? "连接被拒绝" });
        break;
      }

      case EVENT_TYPES.TextStart:
        set((s) => ({
          messages: appendCapped(
            s.messages,
            { id: data.messageId as string, role: "assistant", text: "", streaming: true },
            MAX_IN_MEMORY_MESSAGES,
          ),
          isSpeaking: true,
        }));
        break;

      case EVENT_TYPES.TextDelta:
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === data.messageId ? { ...m, text: m.text + (data.delta as string) } : m,
          ),
          lastTextDeltaAt: event.ts,
          lastTextDelta: data.delta as string,
        }));
        break;

      case EVENT_TYPES.TextEnd:
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === data.messageId
              ? { ...m, text: (data.fullText as string) || m.text, streaming: false }
              : m,
          ),
          isSpeaking: false,
        }));
        break;

      case EVENT_TYPES.StateChange:
        set({ characterState: data.state as CharacterState });
        break;

      case EVENT_TYPES.Emotion:
        set({ emotion: data.emotion as Emotion });
        break;

      default:
        // thinking.* / tool.call.* / 未知类型：M0-S1 暂不渲染，保持忽略
        void get();
    }
  },
}));
