/**
 * idleBehaviors —— 静态皮肤闲置小动作（功能清单 2.8，纯函数）。
 *
 * 「无交互一段时间后随机播放小动作」：张望 / 伸懒腰 / 打盹 / 扭摆。
 * 每个动作是 (elapsedMs) → 变换增量的确定性包络（vitest 直测），
 * 调度（随机挑选/间隔）在组件层消费这些定义。
 *
 * 不打扰用户约束（2.8 验收）：不发声、不遮挡操作——变换幅度刻意收敛
 * （位移 ≤8px、旋转 ≤0.12rad≈7°），不会溢出窗口边界；播放不打断对话。
 *
 * 仅静态路径：Live2D 的小动作走模型动作组（motion groups），依模型而异，
 * 由状态机（stateMachine）按状态调度，不在此层重复。
 */

/** 闲置判定：距最近一次用户交互（点击/光标移动/对话进行中）超过此时长。 */
export const IDLE_DELAY_MS = 20_000;
/** 相邻两次小动作的间隔区间（ms，随机取）。 */
export const IDLE_MIN_GAP_MS = 12_000;
export const IDLE_MAX_GAP_MS = 30_000;

/** 动作变换增量：dx/dy/rotation 叠加，sx/sy 乘算（1 = 无效果）。 */
export interface IdleDelta {
  dx: number;
  dy: number;
  rotation: number;
  sx: number;
  sy: number;
}

export type IdleActionId = "lookAround" | "stretch" | "doze" | "wiggle";

export interface IdleAction {
  id: IdleActionId;
  durationMs: number;
  apply: (elapsedMs: number) => IdleDelta | null;
}

const ZERO: IdleDelta = { dx: 0, dy: 0, rotation: 0, sx: 1, sy: 1 };

/** 张望（2.6s）：视线左右扫 1.5 个来回 + 身体微跟随。 */
function lookAround(elapsedMs: number): IdleDelta | null {
  const T = 2600;
  if (elapsedMs < 0 || elapsedMs >= T) return null;
  const p = elapsedMs / T;
  const sweep = Math.sin(2 * Math.PI * 1.5 * p);
  return { dx: 7 * sweep, dy: 0, rotation: 0.012 * 7 * sweep, sx: 1, sy: 1 };
}

/** 伸懒腰（1.8s）：纵向拉伸 + 横向收窄 + 微踮脚（dy 向上），钟形包络。 */
function stretch(elapsedMs: number): IdleDelta | null {
  const T = 1800;
  if (elapsedMs < 0 || elapsedMs >= T) return null;
  const p = Math.min(1, (elapsedMs / T) * 1.15); // 略提前到位，尾部平滑回落
  const e = Math.sin(Math.PI * p);
  return { dx: 0, dy: -4 * e, rotation: 0.02 * e, sx: 1 - 0.06 * e, sy: 1 + 0.1 * e };
}

/** 打盹（4.2s）：前 90% 缓慢垂头（下移+微倾+微缩），末 10% 惊醒抖动。 */
function doze(elapsedMs: number): IdleDelta | null {
  const T = 4200;
  if (elapsedMs < 0 || elapsedMs >= T) return null;
  const p = elapsedMs / T;
  const e = Math.min(1, p * 10); // 0.1 内进入垂头姿态
  if (p < 0.9) {
    return { dx: 0, dy: 3 * e, rotation: 0.05 * e, sx: 1 - 0.015 * e, sy: 1 - 0.02 * e };
  }
  // 惊醒：垂头姿态上叠加衰减抖动，包络收敛回 ZERO（不突兀截断）
  const q = (p - 0.9) / 0.1;
  const shake = Math.sin(2 * Math.PI * 3 * q) * (1 - q);
  const fade = 1 - q;
  return {
    dx: 2 * shake,
    dy: 3 * fade,
    rotation: 0.05 * fade + 0.04 * shake,
    sx: 1 - 0.015 * fade,
    sy: 1 - 0.02 * fade,
  };
}

/** 扭摆（1.2s）：左右摇摆两下，衰减正弦（欢快感的收尾姿态）。 */
function wiggle(elapsedMs: number): IdleDelta | null {
  const T = 1200;
  if (elapsedMs < 0 || elapsedMs >= T) return null;
  const p = elapsedMs / T;
  const decay = 1 - p;
  const osc = Math.sin(2 * Math.PI * 2.2 * p);
  return { dx: 3 * osc * decay, dy: 0, rotation: 0.09 * osc * decay, sx: 1, sy: 1 };
}

export const IDLE_ACTIONS: readonly IdleAction[] = [
  { id: "lookAround", durationMs: 2600, apply: lookAround },
  { id: "stretch", durationMs: 1800, apply: stretch },
  { id: "doze", durationMs: 4200, apply: doze },
  { id: "wiggle", durationMs: 1200, apply: wiggle },
];

/** 下一次小动作的间隔（ms，区间内随机）。 */
export function nextIdleGap(): number {
  return IDLE_MIN_GAP_MS + Math.random() * (IDLE_MAX_GAP_MS - IDLE_MIN_GAP_MS);
}

/** 随机挑一个动作；exclude 避免连续重复同一个（观感更自然）。 */
export function pickIdleAction(exclude?: IdleActionId): IdleAction {
  const pool = exclude === undefined ? IDLE_ACTIONS : IDLE_ACTIONS.filter((a) => a.id !== exclude);
  return pool[Math.floor(Math.random() * pool.length)] ?? IDLE_ACTIONS[0];
}

/** 测试/诊断用：零增量基准。 */
export const IDLE_ZERO: Readonly<IdleDelta> = ZERO;
