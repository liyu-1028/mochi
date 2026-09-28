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
  type CompanionSignalData,
  type IntentDecision,
  type SignalKind,
  type SignalSalience,
  type ToolConfirmData,
} from "@mochi/protocol";
import { useCallback, useEffect, useRef } from "react";
import { useAttentionSignals } from "./useAttentionSignals";
import { sessionApi } from "../api/configClient";
import { DEFAULT_SIDECAR_PORT, getRuntimePort } from "../api/sidecarRuntime";
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

  /** 危险工具确认（M1-S4，6.5）：唤醒服务端挂起中的回合。
      remember 仅 allow 生效（协议只定义「总是允许」）。 */
  const confirmTool = useCallback(
    (runId: string, toolCallId: string, decision: "allow" | "deny", remember = false): void => {
      const data: ToolConfirmData = { runId, toolCallId, decision, remember };
      clientRef.current?.send(createCommand(COMMAND_TYPES.ToolConfirm, data));
    },
    [],
  );

  /** 陪伴信号上报（M-D）：idle/focus 等环境事实 → 服务端注意力引擎裁决 */
  const sendSignal = useCallback(
    (
      kind: SignalKind,
      salience: SignalSalience,
      payload: Record<string, unknown>,
      opts?: { dedupeKey?: string; notBefore?: number; expiresAt?: number },
    ): void => {
      const data: CompanionSignalData = {
        signalId: crypto.randomUUID(),
        kind,
        occurredAt: Date.now(),
        salience,
        payload,
        ...opts,
      };
      // dev 反馈：控制台注入信号时可见确认（GUI 实测/手工验证用）
      if (import.meta.env.DEV) {
        console.info(
          `[mochi] companion.signal 已发送 kind=${kind} signalId=${data.signalId.slice(0, 8)}`,
        );
      }
      clientRef.current?.send(createCommand(COMMAND_TYPES.CompanionSignal, data));
    },
    [],
  );

  /** ask 快速操作回传（M-D）：later=稍后 / dismiss=不用提醒 / now=现在处理。
      本地立即收起操作条；服务端引擎按决定记账（snooze/主题冷却/触发）。 */
  const respondIntent = useCallback(
    (intentId: string, decision: IntentDecision): void => {
      useConversation.getState().clearPendingIntent();
      sendSignal("intent_response", 0, { intentId, decision });
    },
    [sendSignal],
  );

  // 环境信号（M-D D3）：闲置与连续活跃上报（引擎 idle→silent 只记账；
  // focus 连续活跃超阈触发休息提醒 ask）
  useAttentionSignals(sendSignal);

  // DEV 观测/驱动钩子（M-D GUI 实测用，沿用 __mochiDirector 先例）：
  // 信号必须走前端自身连接（事件只回给提交方连接），测试经此注入
  if (import.meta.env.DEV) {
    (window as unknown as Record<string, unknown>).__mochiConn = { sendSignal, respondIntent };
  }

  return { sendText, cancelRun, interruptRun, confirmTool, respondIntent, sendSignal };
}

/**
 * sidecar WS 地址：VITE_WS_URL 覆盖 > runtime.json 发现端口 > 默认 8199。
 * 发现端口可能晚于首屏到达——App.tsx 订阅端口更新后以新 url 触发重连。
 */
export function resolveWsUrl(): string {
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL;
  return `ws://127.0.0.1:${getRuntimePort() ?? DEFAULT_SIDECAR_PORT}/ws`;
}
