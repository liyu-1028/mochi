/**
 * 视线跟随（功能清单 2.4 一半）：光标位置 → 眼球参数归一化目标。
 *
 * 纯函数内核：以舞台中心为原点归一化到 [-1, 1]，乘灵敏度避免眼球贴边。
 * 组件层每帧 lerp 逼近目标后写 ParamEyeBallX/Y（含状态机 gazeOffsetY）。
 */

/** 灵敏度：光标到舞台边缘时眼球约到 60% 行程，观感更自然 */
export const GAZE_SENSITIVITY = 0.6;

export interface GazeTarget {
  x: number;
  y: number;
}

export interface StageRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

const clamp = (v: number, limit: number) => Math.min(limit, Math.max(-limit, v));

/** 光标页面坐标 → 归一化视线目标（舞台中心为 0,0） */
export function normalizeGaze(
  cursorX: number,
  cursorY: number,
  rect: StageRect,
  sensitivity: number = GAZE_SENSITIVITY,
): GazeTarget {
  if (rect.width <= 0 || rect.height <= 0) return { x: 0, y: 0 };
  const nx = (cursorX - (rect.left + rect.width / 2)) / (rect.width / 2);
  // 屏幕 Y 向下为正，Live2D ParamEyeBallY 向上为正 → 取反
  const ny = -(cursorY - (rect.top + rect.height / 2)) / (rect.height / 2);
  // `|| 0` 消除 -0（严格相等断言与参数写入都更干净）
  return { x: clamp(nx, 1) * sensitivity || 0, y: clamp(ny, 1) * sensitivity || 0 };
}

/** 每帧向目标逼近的 lerp 系数（60fps 下约 8 帧到位，无跳变） */
export const GAZE_LERP = 0.12;

export function lerpGaze(
  current: GazeTarget,
  target: GazeTarget,
  t: number = GAZE_LERP,
): GazeTarget {
  return {
    x: current.x + (target.x - current.x) * t,
    y: current.y + (target.y - current.y) * t,
  };
}
