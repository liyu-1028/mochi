/**
 * voiceEvents —— [voice] 配置变更事件总线（M1-S2）。
 *
 * 托盘静音/设置面板经 putVoice 写盘后 dispatch；useTTS 监听后立即
 * 停播或恢复；Tauri 事件负责跨窗口通知，接收方只派发本地事件、不再次广播。
 */
import { emit, listen } from "@tauri-apps/api/event";
import { EVENT_VOICE_CHANGED } from "../panelWindow";

export const voiceEvents = new EventTarget();
const source = crypto.randomUUID();
let initialization: Promise<void> | null = null;

function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** 主窗口与独立面板在渲染前各注册一次，避免配置已更新但收不到通知。 */
export function initVoiceEventListener(): Promise<void> {
  if (!isTauri()) return Promise.resolve();
  initialization ??= listen<{ source: string }>(EVENT_VOICE_CHANGED, (event) => {
    if (event.payload?.source !== source) voiceEvents.dispatchEvent(new Event("voice-changed"));
  })
    .then(() => undefined)
    .catch((error: unknown) => console.warn("[mochi] 语音设置同步初始化失败：", error));
  return initialization;
}

export function notifyVoiceChanged(): void {
  voiceEvents.dispatchEvent(new Event("voice-changed"));
  if (isTauri()) void emit(EVENT_VOICE_CHANGED, { source }).catch(() => {});
}
