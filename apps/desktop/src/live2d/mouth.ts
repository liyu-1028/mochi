/**
 * 口型驱动（功能清单 2.3 简化方案：text.delta 到达节奏 → 嘴巴开合；
 * M1-S2 起 2.7 音量驱动：播报期 RMS 音量经 volumeToOpen 直驱开度）。
 *
 * 算法纯函数化便于 vitest：
 * - onDelta：每个 delta 触发张嘴，幅度 ∝ delta 长度，进入衰减窗口
 * - stepMouth：窗口内保持张嘴，窗口结束按帧指数衰减平滑闭合（~200ms）
 * - volumeToOpen：AnalyserNode RMS 音量 → 开度（线性放大封顶）
 */

/** 张嘴保持窗口：连续流式 delta（30–80ms 间隔）内维持开度 */
export const MOUTH_DECAY_WINDOW_MS = 80;
/** 衰减期每帧逼近目标的比例（60fps 下约 3 帧到位） */
export const MOUTH_APPROACH = 0.4;
/** 闭合期每帧剩余开度的乘数（60fps 下约 200ms 闭合） */
export const MOUTH_CLOSE_FACTOR = 0.85;

export interface MouthState {
  /** 当前开度 0~1 */
  open: number;
  /** 目标开度 0~1 */
  target: number;
  /** 剩余保持窗口 ms */
  decayMs: number;
}

export const MOUTH_CLOSED: MouthState = { open: 0, target: 0, decayMs: 0 };

/** delta 到达：按长度决定张嘴幅度（1 字轻张，≥3 字满张） */
export function onDelta(state: MouthState, deltaText: string): MouthState {
  const target = Math.min(1, 0.35 + deltaText.length / 4);
  return { open: state.open, target, decayMs: MOUTH_DECAY_WINDOW_MS };
}

/** 音量驱动口型（2.7）：RMS 音量 0..1 → 开度，线性放大封顶；纯函数直测。 */
export function volumeToOpen(level: number): number {
  return Math.max(0, Math.min(1, level * 1.6));
}

/** 每帧推进：窗口内逼近目标，窗口外平滑闭合 */
export function stepMouth(state: MouthState, deltaMs: number): MouthState {
  if (state.decayMs > 0) {
    const open = state.open + (state.target - state.open) * MOUTH_APPROACH;
    return { open, target: state.target, decayMs: Math.max(0, state.decayMs - deltaMs) };
  }
  if (state.open < 0.01) return MOUTH_CLOSED;
  return { open: state.open * MOUTH_CLOSE_FACTOR, target: 0, decayMs: 0 };
}
