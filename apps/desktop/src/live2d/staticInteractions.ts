/**
 * staticInteractions —— 静态皮肤交互反馈（功能清单 2.4 静态路径，纯函数）。
 *
 * 静态精灵没有眼球/分区参数，用整体变换表达「注意光标」与「被点到」：
 * - gazeLean：光标归一化方向 → 微位移 + 微旋转（朝光标侧倾的「注视感」）；
 * - clickBounce：点击时刻起算的果冻 squash & stretch + 小跳（阻尼余弦，
 *   确定性可单测），包络归零后反应自然结束。
 *
 * 输入 gx/gy 为 gaze.ts 的归一化目标（[-SENSITIVITY, SENSITIVITY]，
 * y 向上为正——与屏幕坐标相反）。
 */

/** 点击弹跳总时长（ms）。 */
export const CLICK_BOUNCE_MS = 700;
/** 弹跳初始形变量（0.16 ≈ 16% 压扁）。 */
export const CLICK_BOUNCE_AMP = 0.16;
/** 横向补偿系数：压扁时变宽（近似体积守恒），拉长时变窄。 */
export const CLICK_BOUNCE_WIDEN = 0.7;
/** 阻尼与震荡频率（次/秒）。 */
export const CLICK_BOUNCE_DECAY = 4.5;
export const CLICK_BOUNCE_OSC_HZ = 1.8;
/** 小跳高度（px，向上为负）。 */
export const CLICK_BOUNCE_HOP = 6;

/** 追踪倾斜幅度：需显著大于闲置浮动（±2px@0.8Hz）才可感知。 */
export const LEAN_DX = 10;
export const LEAN_DY = 4;
export const LEAN_ROT = 0.15; // rad；乘灵敏度 0.6 后峰值 ≈ 5°，肉眼可辨

export interface LeanTransform {
  dx: number;
  dy: number;
  rotation: number;
}

/** 光标方向 → 朝向微变换：光标在右 → 右移 + 右倾；光标在上 → 微上移。
 *  `|| 0` 消除 -0（严格相等断言与变换写入都更干净，同 gaze.ts）。 */
export function gazeLean(gx: number, gy: number): LeanTransform {
  return {
    dx: gx * LEAN_DX || 0,
    dy: -gy * LEAN_DY || 0, // gy 向上为正，屏幕 dy 向下为正 → 取反
    rotation: gx * LEAN_ROT || 0,
  };
}

export interface BounceTransform {
  /** 纵向缩放系数（<1 压扁）。 */
  sy: number;
  /** 横向缩放系数（>1 变宽）。 */
  sx: number;
  /** 垂直位移（px，负 = 上跳）。 */
  hop: number;
}

/** 点击后 t=elapsedMs 的果冻弹跳；超时返回 null（反应结束）。 */
export function clickBounce(
  elapsedMs: number,
  durationMs: number = CLICK_BOUNCE_MS,
): BounceTransform | null {
  if (elapsedMs < 0 || elapsedMs >= durationMs) return null;
  const t = elapsedMs / 1000;
  const squash =
    CLICK_BOUNCE_AMP *
    Math.exp(-CLICK_BOUNCE_DECAY * t) *
    Math.cos(2 * Math.PI * CLICK_BOUNCE_OSC_HZ * t);
  const tt = elapsedMs / durationMs;
  return {
    sy: 1 - squash,
    sx: 1 + squash * CLICK_BOUNCE_WIDEN,
    hop: -CLICK_BOUNCE_HOP * Math.sin(Math.PI * tt) * Math.exp(-1.5 * tt),
  };
}
