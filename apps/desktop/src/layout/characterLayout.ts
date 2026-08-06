/**
 * characterLayout —— 窗口/角色布局倒置的纯函数事实源（可直测）。
 *
 * 倒置前：窗口固定 320×400 → canvas 跟随 → 模型缩放适配 canvas；
 * 倒置后：设计常量定角色目标像素高 → 反推 scale → 模型包围盒 → 窗口尺寸，
 * OS 窗口经 applyWindowLayout 同步，真正「只有角色那么大」。
 *
 * 窗口纵向结构（与 styles.css 一一对应，见 CHROME_HEIGHT）：
 *   PAD(顶) + 头顶留白区 + 角色高 + gap + dock + PAD(底)
 * 气泡渲染在角色图层之上、头部高度侧向贴近（headGap ≈ 头半宽），
 * 出现/消失不改变窗口尺寸。
 */

/** 角色目标像素高（逻辑 px）：桌面存在感基线。 */
export const TARGET_CHARACTER_HEIGHT = 280;
/** 宽屏/横版模型 clamp：防窗口被拉得过宽。 */
export const MAX_CHARACTER_WIDTH = 360;
/** 角色头顶留给气泡叠层的空白区高度。 */
export const BUBBLE_HEADROOM = 96;
/** 气泡内缘距窗口中线的间距占角色宽比例（头半宽经验值）：贴近头部又不遮脸。 */
export const HEAD_GAP_RATIO = 0.12;
/** 气泡顶边相对角色头顶的上移重叠量，视觉更贴合头部。 */
export const BUBBLE_HEAD_OVERLAP = 4;
/** 底部 dock 槽位高（styles.css .app__dock）。 */
export const DOCK_HEIGHT = 46;
/** .app 内边距（styles.css .app padding）。 */
export const PAD = 8;
/** .app 的 stage 与 dock 之间 gap（styles.css .app gap）。 */
export const GAP = 4;

/** 非角色区纵向开销 = 顶 PAD + gap + dock + 底 PAD，与 styles.css 同源。 */
export const CHROME_HEIGHT = PAD + GAP + DOCK_HEIGHT + PAD;

export interface CharacterLayout {
  winW: number;
  winH: number;
  scale: number;
  charW: number;
  charH: number;
  /** 气泡顶边（相对 .app）：角色头顶略上移重叠，侧向贴近头部。 */
  bubbleTop: number;
  /** 气泡内缘与窗口中线的水平间距（≈头半宽）：侧向贴头且不遮脸。 */
  headGap: number;
}

/** 模型原始尺寸 → 布局：scale 取「目标高」与「最大宽」两个约束的较小者。 */
export function computeCharacterLayout(modelW: number, modelH: number): CharacterLayout {
  const scale = Math.min(TARGET_CHARACTER_HEIGHT / modelH, MAX_CHARACTER_WIDTH / modelW);
  const charW = modelW * scale;
  const charH = modelH * scale;
  return {
    winW: Math.ceil(charW) + PAD * 2,
    winH: BUBBLE_HEADROOM + Math.ceil(charH) + CHROME_HEIGHT,
    scale,
    charW,
    charH,
    bubbleTop: PAD + BUBBLE_HEADROOM - BUBBLE_HEAD_OVERLAP,
    headGap: Math.round(charW * HEAD_GAP_RATIO),
  };
}

/** Live2D 降级（CharacterBadge 占位）时的兜底布局：沿用现状 320×400 语义。 */
export const FALLBACK_LAYOUT: CharacterLayout = {
  winW: 320,
  winH: 400,
  scale: 1,
  charW: 320,
  charH: 400,
  bubbleTop: PAD + BUBBLE_HEADROOM - BUBBLE_HEAD_OVERLAP,
  headGap: Math.round(320 * HEAD_GAP_RATIO),
};

/** resize 时保持底边（角色脚底）屏幕位置不变；输入输出均为物理 px。 */
export function anchorBottomY(currentY: number, oldOuterH: number, newOuterH: number): number {
  return currentY + (oldOuterH - newOuterH);
}
