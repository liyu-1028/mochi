/**
 * useMochiConnection —— WebSocketClient 与 conversation store 的装配点。
 *
 * 组件卸载时自动断开；sendText/cancelRun 是 UI 仅有的两个业务动作。
 */
import {
  COMMAND_TYPES,
  createCommand,
  type ChatCancelData,
  type ChatSendData,
} from "@mochi/protocol";
import { useCallback, useEffect, useRef } from "react";
import { useConversation } from "../store/conversation";
import { WebSocketClient } from "../ws/WebSocketClient";

const APP_CLIENT_INFO = { name: "mochi-desktop", version: "0.1.0" };
const M0_SESSION_ID = "default"; // M0 单会话（多会话见 S5）

export function useMochiConnection(url: string) {
  const clientRef = useRef<WebSocketClient | null>(null);

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

  const sendText = useCallback((text: string): void => {
    const trimmed = text.trim();
    if (!trimmed) return;
    const data: ChatSendData = {
      runId: crypto.randomUUID(),
      sessionId: M0_SESSION_ID,
      text: trimmed,
    };
    useConversation.getState().addUserMessage(trimmed);
    clientRef.current?.send(createCommand(COMMAND_TYPES.ChatSend, data));
  }, []);

  const cancelRun = useCallback((runId: string): void => {
    const data: ChatCancelData = { runId };
    clientRef.current?.send(createCommand(COMMAND_TYPES.ChatCancel, data));
  }, []);

  return { sendText, cancelRun };
}

/** sidecar 连接地址：dev 模式手动起 sidecar（默认 8199），Tauri 集成后可经 env 覆盖。 */
export function resolveWsUrl(): string {
  return import.meta.env.VITE_WS_URL ?? "ws://127.0.0.1:8199/ws";
}
