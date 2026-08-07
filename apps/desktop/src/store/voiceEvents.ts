/**
 * voiceEvents —— [voice] 配置变更事件总线（M1-S2）。
 *
 * 托盘静音/设置面板经 putVoice 写盘后 dispatch；useTTS 监听后立即
 * 停播或恢复（配置事实源在 sidecar，前端无共享 store，同窗口内事件桥接）。
 */
export const voiceEvents = new EventTarget();

export function notifyVoiceChanged(): void {
  voiceEvents.dispatchEvent(new Event("voice-changed"));
}
