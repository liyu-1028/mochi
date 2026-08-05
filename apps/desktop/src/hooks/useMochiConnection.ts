/**
 * useMochiConnection —— WebSocketClient 与 conversation store 的装配点。
 *
 * 组件卸载时自动断开；sendText/cancelRun/interruptRun 是 UI 仅有的业务动作
 * （interrupt 供 S2 TTS 播报打断使用，当前无调用方）。
 */
import {
  COMMAND_TYPES,
  createCommand,
  type ChatCancelData,
  type ChatInterruptData,
  type ChatSendData,
} from "@mochi/protocol";
import { useCallback, useEffect, useRef } from "react";
import { sessionApi } from "../api/configClient";
import { historyToMessages, useConversation } from "../store/conversation";
import { WebSocketClient } from "../ws/WebSocketClient";

const APP_CLIENT_INFO = { name: "mochi-desktop", version: "0.1.0" };

/** 默认会话 id：M1-S1 单会话多轮（多会话为后续迭代）。 */
export const DEFAULT_SESSION_ID = "default";

export function useMochiConnection(url: string) {
  const clientRef = useRef<WebSocketClient | null>(null);
  // 历史回显只做一次（重连不重复拉），用 ref 而非 state 避免多余渲染
  const hydratedRef = useRef(false);
  const status = useConversation((s) => s.status);

  useEffect(() => {
    const client = new WebSocketClient({
      url,
      clientInfo: APP_CLIENT_INFO,
      onEvent: (event) => useConversation.getState().applyEvent(event),
      onStatusChange: (status) => useConversation.getState().setStatus(status),
    });
    clientRef.current = client;
    client.connect();
    return () => {
      client.close();
      clientRef.current = null;
    };
  }, [url]);

  // 连接就绪后回显历史（4.3）：重启应用能看到上一轮对话。
  // 失败静默（REST 未就绪/无历史）——不影响对话主链路。
  useEffect(() => {
    if (status !== "connected" || hydratedRef.current) return;
    hydratedRef.current = true;
    sessionApi
      .getMessages(DEFAULT_SESSION_ID)
      .then((history) => {
        if (history.length > 0) {
          useConversation.getState().hydrateHistory(historyToMessages(history));
        }
      })
      .catch(() => undefined);
  }, [status]);

  const sendText = useCallback((text: string): void => {
    const trimmed = text.trim();
    if (!trimmed) return;
    const data: ChatSendData = {
      runId: crypto.randomUUID(),
      sessionId: DEFAULT_SESSION_ID,
      text: trimmed,
    };
    useConversation.getState().addUserMessage(trimmed);
    clientRef.current?.send(createCommand(COMMAND_TYPES.ChatSend, data));
  }, []);

  const cancelRun = useCallback((runId: string): void => {
    const data: ChatCancelData = { runId };
    clientRef.current?.send(createCommand(COMMAND_TYPES.ChatCancel, data));
  }, []);

  /** 打断播报（协议 §4）：停 TTS/展示、保留已生成内容，reason="interrupted"。 */
  const interruptRun = useCallback((runId: string): void => {
    const data: ChatInterruptData = { runId };
    clientRef.current?.send(createCommand(COMMAND_TYPES.ChatInterrupt, data));
  }, []);

  return { sendText, cancelRun, interruptRun };
}

/** sidecar 连接地址：dev 模式手动起 sidecar（默认 8199），Tauri 集成后可经 env 覆盖。 */
export function resolveWsUrl(): string {
  return import.meta.env.VITE_WS_URL ?? "ws://127.0.0.1:8199/ws";
}
