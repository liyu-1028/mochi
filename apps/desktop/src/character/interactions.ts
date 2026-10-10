/**
 * interactions —— Live2D 命中分区差异化反应（功能清单 2.4，纯函数便于单测）。
 *
 * pixi-live2d-display 的 model.hitTest(x, y) 返回命中的分区名数组（模型
 * .cdi3.json 定义，常见 Head/Body；命名依模型而异，此处大小写不敏感匹配）。
 * 分区语义仅对用户导入的 Live2D 模型生效：v0.6.0 起内置皮肤全为静态
 * 精灵图（无分区概念），静态路径维持整体点击反应（已达标）。
 *
 * 反应设计（观感优先、参数保守，E2E 目测微调）：
 * - head（摸头）：happy 眼笑 + 嘴角 + 轻微头偏，正弦包络 1.2s 淡入淡出；
 * - body（戳身体）：身体左右小幅摆动，衰减震荡 0.9s；
 * - 空命中/静态：无反应（点击交互仍走 onActivate 唤起输入框，不变）。
 */

export type HitReaction = "head" | "body" | null;

/** 反应持续时长（ms）。 */
export const HEAD_PAT_MS = 1200;
export const BODY_WIGGLE_MS = 900;

/** 大小写不敏感匹配分区名；Head 优先于 Body（同帧命中取更具体互动）。 */
export function reactionFor(hits: readonly string[]): HitReaction {
  const names = hits.map((h) => h.toLowerCase());
  if (names.some((n) => n.includes("head"))) return "head";
  if (names.some((n) => n.includes("body"))) return "body";
  return null;
}

/** 摸头包络 [0,1]：正弦半周期，头尾平滑归零；超时返回 0。 */
export function headPatEnvelope(elapsedMs: number, durationMs: number = HEAD_PAT_MS): number {
  if (elapsedMs < 0 || elapsedMs >= durationMs) return 0;
  return Math.sin((Math.PI * elapsedMs) / durationMs);
}

/** 戳身体摆角（度）：衰减正弦震荡；超时返回 0。 */
export function bodyWiggleAngle(elapsedMs: number, durationMs: number = BODY_WIGGLE_MS): number {
  if (elapsedMs < 0 || elapsedMs >= durationMs) return 0;
  const t = elapsedMs / durationMs; // 0..1
  const decay = 1 - t;
  return Math.sin(t * Math.PI * 4) * 4 * decay;
}

/** 摸头参数预设（与 EMOTION_PRESETS.happy 同源 + 头部微偏；乘包络后下发）。 */
export const HEAD_PAT_PARAMS: Readonly<Record<string, number>> = {
  ParamEyeLSmile: 1,
  ParamEyeRSmile: 1,
  ParamMouthForm: 1,
};

/** 摸头头部偏角（度）：包络内轻微左右扫动。 */
export function headPatAngleZ(elapsedMs: number, durationMs: number = HEAD_PAT_MS): number {
  const env = headPatEnvelope(elapsedMs, durationMs);
  if (env <= 0) return 0;
  const t = elapsedMs / durationMs;
  return Math.sin(t * Math.PI * 2) * 6 * env;
}
