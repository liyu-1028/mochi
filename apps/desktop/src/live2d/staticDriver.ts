/**
 * 静态皮肤驱动：把 StaticAnimationPlan 翻译成 sprite 变换（每帧 ticker）。
 *
 * 正弦参数设计（避免「廉价感」——feature-list §10 产品风险）：
 * - 漂浮 0.8Hz/2px：轻盈不躁；
 * - 呼吸 0.35Hz/0.8% 缩放：接近真实呼吸节奏，营造「活着」而不明显；
 * - 摇摆 0.2Hz/0.8°：极慢微旋模拟重心偏移；
 * 三轴频率比 4 : 1.75 : 1 非整数倍，避免周期性明显的叠加峰。
 * 说话 = 6Hz 微脉冲（无口型的最小可用表达）；sleeping = 灰度+下移；
 * error = 高频水平抖动（确定性正弦，可单测）。
 */
import type { StaticStageHandle } from "./staticCore";

export interface StaticAnimationPlan {
  float: boolean;
  breathe: boolean;
  sway: boolean;
  talking: boolean;
  sleeping: boolean;
  error: boolean;
  /** 情绪微缩放（emotionMapping.scale，1 = 无情绪表达）。 */
  emotionScale: number;
}

/** 单帧 sprite 变换（纯函数输出，vitest 直测）。 */
export interface StaticTransform {
  dx: number;
  dy: number;
  rotation: number;
  scale: number;
  tint: number;
}

export const STATIC_ANIM_PARAMS = {
  floatFreq: 0.8,
  floatAmp: 2,
  breatheFreq: 0.35,
  breatheAmp: 0.008,
  swayFreq: 0.2,
  swayAmp: 0.014,
  talkFreq: 6,
  talkAmp: 0.015,
  errorFreq: 8,
  errorAmp: 3,
  sleepDy: 4,
  sleepTint: 0x999999,
} as const;

const TWO_PI = Math.PI * 2;

/** (计划, 时刻) → 变换；t 单位秒。纯函数，驱动层仅负责应用。 */
export function computeStaticTransform(plan: StaticAnimationPlan, t: number): StaticTransform {
  const p = STATIC_ANIM_PARAMS;
  let dx = 0;
  let dy = 0;
  let rotation = 0;
  let scale = plan.emotionScale;
  let tint = 0xffffff;

  if (plan.float) dy += Math.sin(t * TWO_PI * p.floatFreq) * p.floatAmp;
  if (plan.breathe) scale *= 1 + Math.sin(t * TWO_PI * p.breatheFreq) * p.breatheAmp;
  if (plan.sway) rotation = Math.sin(t * TWO_PI * p.swayFreq) * p.swayAmp;
  if (plan.talking) scale *= 1 + Math.sin(t * TWO_PI * p.talkFreq) * p.talkAmp;
  if (plan.sleeping) {
    tint = p.sleepTint;
    dy += p.sleepDy;
  }
  if (plan.error) dx = Math.sin(t * TWO_PI * p.errorFreq) * p.errorAmp;

  return { dx, dy, rotation, scale, tint };
}

export interface StaticDriver {
  readonly kind: "static";
  applyPlan(plan: StaticAnimationPlan): void;
  dispose(): void;
}

export function createStaticDriver(stage: StaticStageHandle): StaticDriver {
  const { sprite, app } = stage;
  const baseScale = sprite.scale.x;
  let plan: StaticAnimationPlan = {
    float: false,
    breathe: false,
    sway: false,
    talking: false,
    sleeping: false,
    error: false,
    emotionScale: 1,
  };

  const tick = () => {
    const t = performance.now() / 1000;
    const tr = computeStaticTransform(plan, t);
    // 基准位置每帧重取：窗口 resize（布局倒置）后自动回中
    sprite.x = app.screen.width / 2 + tr.dx;
    sprite.y = app.screen.height + tr.dy;
    sprite.rotation = tr.rotation;
    sprite.scale.set(baseScale * tr.scale);
    sprite.tint = tr.tint;
  };
  app.ticker.add(tick);

  return {
    kind: "static",
    applyPlan(next) {
      plan = next;
    },
    dispose() {
      app.ticker.remove(tick);
    },
  };
}
