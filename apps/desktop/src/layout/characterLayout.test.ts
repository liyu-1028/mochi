/**
 * characterLayout 纯函数测试：布局倒置的尺寸推导与脚底锚定。
 */
import { describe, expect, it } from "vitest";
import {
  BUBBLE_HEADROOM,
  BUBBLE_HEAD_OVERLAP,
  CHROME_HEIGHT,
  FALLBACK_LAYOUT,
  HEAD_GAP_RATIO,
  MAX_CHARACTER_WIDTH,
  MAX_STATIC_UPSCALE,
  PAD,
  TARGET_CHARACTER_HEIGHT,
  anchorBottomY,
  computeCharacterLayout,
} from "./characterLayout";

describe("computeCharacterLayout", () => {
  it("竖版模型：高度约束生效，角色达到目标高", () => {
    const layout = computeCharacterLayout(1000, 2000);
    expect(layout.scale).toBeCloseTo(TARGET_CHARACTER_HEIGHT / 2000, 10);
    expect(layout.charH).toBeCloseTo(TARGET_CHARACTER_HEIGHT, 10);
    expect(layout.charW).toBeCloseTo(140, 10);
    expect(layout.winW).toBe(140 + PAD * 2);
    expect(layout.winH).toBe(BUBBLE_HEADROOM + 280 + CHROME_HEIGHT);
    expect(layout.bubbleTop).toBe(PAD + BUBBLE_HEADROOM - BUBBLE_HEAD_OVERLAP);
    expect(layout.headGap).toBe(Math.round(140 * HEAD_GAP_RATIO));
  });

  it("横版模型：宽度 clamp 生效，角色不超过 MAX_CHARACTER_WIDTH", () => {
    const layout = computeCharacterLayout(4000, 1000);
    expect(layout.charW).toBeCloseTo(MAX_CHARACTER_WIDTH, 10);
    expect(layout.charH).toBeCloseTo(90, 10);
    expect(layout.winW).toBe(360 + PAD * 2);
  });

  it("窗口高度 = 头顶气泡区 + 角色高 + 纵向开销", () => {
    const layout = computeCharacterLayout(800, 1200);
    expect(layout.winH).toBe(BUBBLE_HEADROOM + Math.ceil(layout.charH) + CHROME_HEIGHT);
    expect(layout.winW).toBe(Math.ceil(layout.charW) + PAD * 2);
  });

  it("放大上限：64px 小图 scale 封顶 MAX_STATIC_UPSCALE，不再无限拉大", () => {
    const capped = computeCharacterLayout(64, 64, MAX_STATIC_UPSCALE);
    expect(capped.scale).toBe(MAX_STATIC_UPSCALE);
    expect(capped.charH).toBe(128);
    // 无上限（live2d 路径）保持目标高归一
    const uncapped = computeCharacterLayout(64, 64);
    expect(uncapped.scale).toBeCloseTo(TARGET_CHARACTER_HEIGHT / 64, 10);
  });

  it("放大上限：常规尺寸不受 cap 影响（snj 形状 1.34x < 2）", () => {
    const layout = computeCharacterLayout(148, 209, MAX_STATIC_UPSCALE);
    expect(layout.scale).toBeCloseTo(TARGET_CHARACTER_HEIGHT / 209, 10);
    expect(layout.charH).toBeCloseTo(TARGET_CHARACTER_HEIGHT, 10);
  });
});

describe("anchorBottomY", () => {
  it("resize 后底边屏幕位置不变", () => {
    const y = anchorBottomY(100, 800, 600);
    expect(y).toBe(300);
    expect(y + 600).toBe(100 + 800); // 底边守恒
  });

  it("长高时窗口顶边上移", () => {
    expect(anchorBottomY(100, 600, 800)).toBe(-100);
  });

  it("高度不变时 y 不变", () => {
    expect(anchorBottomY(42, 700, 700)).toBe(42);
  });
});

describe("FALLBACK_LAYOUT", () => {
  it("降级沿用现状 320×400 语义", () => {
    expect(FALLBACK_LAYOUT.winW).toBe(320);
    expect(FALLBACK_LAYOUT.winH).toBe(400);
  });
});
