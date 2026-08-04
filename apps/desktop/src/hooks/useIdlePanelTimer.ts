/**
 * useIdlePanelTimer —— 聊天输入条的"无悬停自动隐藏"定时器。
 *
 * 设计动机：点击 Mochi 唤起输入条后，用户若未继续交互（不悬停、不打字、
 * 不接收回复），输入条应自动收起，避免挡住角色视线。
 *
 * 用法（ChatToggle.tsx）：
 * ```ts
 * useIdlePanelTimer({
 *   paused: !open || closing,
 *   onIdle: handleClose,
 * });
 * ```
 *
 * - paused 为 true 时：清理 timer、不重新挂（整体开关）
 * - paused 为 false 时：挂 setTimeout，依赖变更或组件卸载都重置
 *
 * 纯函数 shouldKeepPanelOpen 单独导出供单测覆盖所有"是否暂停"组合；
 * hook 本身只做定时器挂/卸，不引入任何 Tauri 专用 API（DOM timer 即可）。
 */
import { useEffect } from "react";

export const IDLE_TIMEOUT_MS = 5000; // 默认 idle 超时（毫秒）

export type PanelActivity = {
  isHovered: boolean;
  isFocused: boolean;
  hasPendingInput: boolean;
  hasActiveRun: boolean;
};

/**
 * 任一"用户在交互或正在接收回复"信号为真，计时器应暂停。
 * 纯函数便于 vitest 直接覆盖（hooks 目录测试基础设施是 node 环境，
 * 不挂 React 渲染）。
 */
export function shouldKeepPanelOpen(a: PanelActivity): boolean {
  return a.isHovered || a.isFocused || a.hasPendingInput || a.hasActiveRun;
}

interface UseIdlePanelTimerOptions {
  /** true 时不挂定时器（面板未 open 或正在播放关闭动画） */
  paused: boolean;
  /** 计时器到点时触发 */
  onIdle: () => void;
  /** 超时阈值，默认 5000ms */
  timeoutMs?: number;
}

export function useIdlePanelTimer({
  paused,
  onIdle,
  timeoutMs = IDLE_TIMEOUT_MS,
}: UseIdlePanelTimerOptions): void {
  useEffect(() => {
    if (paused) return;
    const handle = window.setTimeout(onIdle, timeoutMs);
    return () => window.clearTimeout(handle);
  }, [paused, onIdle, timeoutMs]);
}
