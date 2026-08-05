/**
 * CharacterMenu 纯函数测试：
 * - getMenuSize：菜单尺寸与 Mochi 窗口为百分比关系（宽 50%、高 32%）；
 * - clampMenuPosition：菜单不溢出窗口。
 */
import { describe, expect, it } from "vitest";
import {
  MENU_HEIGHT_RATIO,
  MENU_WIDTH_RATIO,
  clampMenuPosition,
  getMenuSize,
} from "./CharacterMenu";

const WIN_W = 320;
const WIN_H = 400;
const MENU = getMenuSize(WIN_W, WIN_H);

function clamp(x: number, y: number) {
  return clampMenuPosition(x, y, MENU.width, MENU.height, WIN_W, WIN_H);
}

describe("getMenuSize", () => {
  it("设计尺寸 320×400 下为 160×128", () => {
    expect(MENU).toEqual({ width: 160, height: 128 });
  });

  it("随窗口等比缩放（百分比关系）", () => {
    expect(getMenuSize(640, 800)).toEqual({ width: 320, height: 256 });
    expect(getMenuSize(160, 200)).toEqual({ width: 80, height: 64 });
  });

  it("比例为 50% / 32%", () => {
    expect(MENU_WIDTH_RATIO).toBe(0.5);
    expect(MENU_HEIGHT_RATIO).toBe(0.32);
  });
});

describe("clampMenuPosition", () => {
  it("窗口中部原样返回", () => {
    expect(clamp(100, 150)).toEqual({ x: 100, y: 150 });
  });

  it("靠近右缘时向左收回", () => {
    const pos = clamp(310, 100);
    expect(pos.x).toBeLessThanOrEqual(WIN_W - MENU.width - 8);
    expect(pos.x).toBeGreaterThanOrEqual(8);
  });

  it("靠近下缘时向上收回", () => {
    const pos = clamp(50, 395);
    expect(pos.y).toBeLessThanOrEqual(WIN_H - MENU.height - 8);
    expect(pos.y).toBeGreaterThanOrEqual(8);
  });

  it("负坐标钳制到最小边距", () => {
    expect(clamp(-50, -50)).toEqual({ x: 8, y: 8 });
  });

  it("右下角极端坐标不溢出", () => {
    const pos = clamp(1000, 1000);
    expect(pos.x + MENU.width).toBeLessThanOrEqual(WIN_W - 8);
    expect(pos.y + MENU.height).toBeLessThanOrEqual(WIN_H - 8);
  });
});
