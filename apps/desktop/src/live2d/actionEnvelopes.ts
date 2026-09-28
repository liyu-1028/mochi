/**
 * actionEnvelopes —— 静态皮肤语义动作包络（M-A，纯函数）。
 *
 * 12 个语义词表动作（协议规范 §11）的静态皮肤实现：与 idleBehaviors 同风格的
 * 确定性包络（(elapsedMs) → 变换增量 | null），vitest 直测；调度（何时播放）
 * 属 M-B Action Director，本模块只定义「动作长什么样」。
 *
 * 幅度分级预算（2026-09-28 用户实测反馈：原 8px 档反馈不明显）：
 * - 闲置复用动作（look_around/stretch/doze，背景生命感）：保持 2.8 克制档 ≤8px/0.12rad；
 * - 反馈动作（celebrate/nod/wave/shake_head/surprised/listen/think/comfort）：
 *   放大到 ≤18px/0.2rad——用户可感知的应答，不再与背景闲置同档。
 */

import { IDLE_ACTIONS, IDLE_ZERO, type IdleAction, type IdleDelta } from "./idleBehaviors";

export interface ActionEnvelope {
  id: string;
  durationMs: number;
  /** 返回 null 表示动作已结束（one-shot 语义）；增量叠加到当前变换上 */
  apply: (elapsedMs: number) => IdleDelta | null;
}

/** 钟形包络：0→1→0，用于「起势-展开-收势」类动作。 */
function bell(p: number): number {
  return Math.sin(Math.PI * Math.min(1, Math.max(0, p)));
}

/** 复用 idleBehaviors 同名包络（camelCase → snake_case 映射）。 */
function fromIdleAction(id: IdleAction["id"]): ActionEnvelope {
  const def = IDLE_ACTIONS.find((a) => a.id === id);
  if (!def) throw new Error(`idleBehaviors 缺少动作定义：${id}`);
  return { id: def.id, durationMs: def.durationMs, apply: def.apply };
}

/** 张望：复用闲置张望（2.6s，视线左右扫 + 身体微跟随）。 */
const lookAround = fromIdleAction("lookAround");
/** 伸懒腰：复用闲置伸懒腰（1.8s，纵拉 + 微踮脚）。 */
const stretch = fromIdleAction("stretch");
/** 打盹：复用闲置打盹（4.2s，垂头 + 末尾惊醒抖动）。 */
const doze = fromIdleAction("doze");

/** idle_neutral（0ms）：兜底终点，无变换——保持当前状态 loop 原样。 */
const idleNeutral: ActionEnvelope = {
  id: "idle_neutral",
  durationMs: 0,
  apply: () => null,
};

/** think（3.2s）：歪头沉思——缓慢侧倾 + 轻微上扬，钟形展开后保持再回落。 */
function think(elapsedMs: number): IdleDelta | null {
  const T = 3200;
  if (elapsedMs < 0 || elapsedMs >= T) return null;
  const p = elapsedMs / T;
  const hold = Math.min(1, p * 6) * Math.min(1, (1 - p) * 6); // 快进慢出平台形
  const sway = Math.sin(elapsedMs / 400) * 0.05 * hold;
  return { dx: 0, dy: -2 * hold, rotation: (0.1 + sway) * hold, sx: 1, sy: 1 };
}

/** listen（2.2s）：侧耳倾听——反向轻倾 + 两下小点头。 */
function listen(elapsedMs: number): IdleDelta | null {
  const T = 2200;
  if (elapsedMs < 0 || elapsedMs >= T) return null;
  const p = elapsedMs / T;
  const lean = bell(p * 0.5 + 0.25) * 0.1;
  const bob = Math.abs(Math.sin(2 * Math.PI * 2 * p)) * 4 * bell(p);
  return { dx: 0, dy: -bob, rotation: lean, sx: 1, sy: 1 };
}

/** wave（1.4s）：打招呼——左右摇摆两下（衰减正弦，欢快收尾）。 */
function wave(elapsedMs: number): IdleDelta | null {
  const T = 1400;
  if (elapsedMs < 0 || elapsedMs >= T) return null;
  const p = elapsedMs / T;
  const decay = 1 - p * 0.6;
  const osc = Math.sin(2 * Math.PI * 2.5 * p);
  return {
    dx: 11 * osc * decay,
    dy: -3 * bell(p),
    rotation: 0.16 * osc * decay,
    sx: 1,
    sy: 1,
  };
}

/** nod（0.9s）：点头——纵向下沉两下（幅度递减）。 */
function nod(elapsedMs: number): IdleDelta | null {
  const T = 900;
  if (elapsedMs < 0 || elapsedMs >= T) return null;
  const p = elapsedMs / T;
  const dip = Math.abs(Math.sin(2 * Math.PI * 2 * p)) * (1 - p * 0.5);
  return { dx: 0, dy: 9 * dip, rotation: 0.05 * dip, sx: 1 + 0.02 * dip, sy: 1 - 0.06 * dip };
}

/** shake_head（1.0s）：摇头——水平摆动两下半（幅度递减）。 */
function shakeHead(elapsedMs: number): IdleDelta | null {
  const T = 1000;
  if (elapsedMs < 0 || elapsedMs >= T) return null;
  const p = elapsedMs / T;
  const decay = 1 - p * 0.5;
  const osc = Math.sin(2 * Math.PI * 2.5 * p);
  return { dx: 13 * osc * decay, dy: 0, rotation: 0.04 * osc * decay, sx: 1, sy: 1 };
}

/** celebrate（1.2s）：庆祝——两次小跳 + 微放大，落地回正。 */
function celebrate(elapsedMs: number): IdleDelta | null {
  const T = 1200;
  if (elapsedMs < 0 || elapsedMs >= T) return null;
  const p = elapsedMs / T;
  const hopPhase = (p * 2) % 1;
  const hop = Math.sin(Math.PI * hopPhase) * (p < 0.5 ? 1 : 0.7);
  return {
    dx: 0,
    dy: -14 * hop,
    rotation: 0.08 * Math.sin(2 * Math.PI * p),
    sx: 1 + 0.1 * bell(p),
    sy: 1 + 0.14 * bell(p),
  };
}

/** comfort（2.0s）：安慰——缓缓前倾靠近再退回（钟形，收敛温和）。 */
function comfort(elapsedMs: number): IdleDelta | null {
  const T = 2000;
  if (elapsedMs < 0 || elapsedMs >= T) return null;
  const p = elapsedMs / T;
  const e = bell(p);
  return { dx: 4 * e, dy: 4 * e, rotation: 0.06 * e, sx: 1 + 0.04 * e, sy: 1 - 0.04 * e };
}

/** surprised（0.7s）：吃惊——快速弹起放大再回落（前快后缓）。 */
function surprised(elapsedMs: number): IdleDelta | null {
  const T = 700;
  if (elapsedMs < 0 || elapsedMs >= T) return null;
  const p = elapsedMs / T;
  const e = Math.pow(1 - p, 1.6); // 冲击后指数回落
  const kick = p < 0.15 ? (p / 0.15) * 1 : 1;
  return { dx: 0, dy: -8 * e * kick, rotation: 0, sx: 1 + 0.16 * e * kick, sy: 1 + 0.2 * e * kick };
}

/** 语义词表全集（协议规范 §11）的静态包络注册表。 */
export const ACTION_ENVELOPES: Readonly<Record<string, ActionEnvelope>> = {
  idle_neutral: idleNeutral,
  look_around: lookAround,
  think: { id: "think", durationMs: 3200, apply: think },
  listen: { id: "listen", durationMs: 2200, apply: listen },
  wave: { id: "wave", durationMs: 1400, apply: wave },
  nod: { id: "nod", durationMs: 900, apply: nod },
  shake_head: { id: "shake_head", durationMs: 1000, apply: shakeHead },
  celebrate: { id: "celebrate", durationMs: 1200, apply: celebrate },
  comfort: { id: "comfort", durationMs: 2000, apply: comfort },
  surprised: { id: "surprised", durationMs: 700, apply: surprised },
  stretch,
  doze,
};

/** 零增量基准（测试/诊断用）。 */
export const ENVELOPE_ZERO: Readonly<IdleDelta> = IDLE_ZERO;
