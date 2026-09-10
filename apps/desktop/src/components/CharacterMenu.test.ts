/**
 * CharacterMenu 纯函数测试：
 * - getMenuSize：宽度固定 160，高度随条目数推导（dev 构建含 devtools 多一项）；
 * - clampMenuPosition：菜单不溢出窗口。
 */
import { describe, expect, it } from "vitest";
import { MENU_HEIGHT, MENU_WIDTH, clampMenuPosition, getMenuSize } from "./CharacterMenu";

const WIN_W = 320;
const WIN_H = 400;
const MENU = getMenuSize();

function clamp(x: number, y: number) {
  return clampMenuPosition(x, y, MENU.width, MENU.height, WIN_W, WIN_H);
}

describe("getMenuSize", () => {
  it("固定宽 160，高随条目数推导（32 + 36n，dev 构建含 devtools 项）", () => {
    expect(MENU).toEqual({ width: 160, height: MENU_HEIGHT });
    expect(MENU_HEIGHT).toBeGreaterThanOrEqual(176); // 4 项基准，dev 构建更高
  });

  it("常量与函数同源", () => {
    expect(MENU_WIDTH).toBe(160);
    expect(getMenuSize().height).toBe(MENU_HEIGHT);
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

  it("窗口比菜单更窄时不抛错且贴左缘", () => {
    const pos = clampMenuPosition(50, 50, MENU.width, MENU.height, 120, 100);
    expect(pos.x).toBe(8);
    expect(pos.y).toBe(8);
  });
});
