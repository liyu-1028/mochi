/**
 * CharacterMenu clamp 纯函数测试：菜单不溢出 320×400 窗口。
 */
import { describe, expect, it } from "vitest";
import { MENU_HEIGHT, MENU_WIDTH, clampMenuPosition } from "./CharacterMenu";

const WIN_W = 320;
const WIN_H = 400;

function clamp(x: number, y: number) {
  return clampMenuPosition(x, y, MENU_WIDTH, MENU_HEIGHT, WIN_W, WIN_H);
}

describe("clampMenuPosition", () => {
  it("窗口中部原样返回", () => {
    expect(clamp(100, 150)).toEqual({ x: 100, y: 150 });
  });

  it("靠近右缘时向左收回", () => {
    const pos = clamp(310, 100);
    expect(pos.x).toBeLessThanOrEqual(WIN_W - MENU_WIDTH - 8);
    expect(pos.x).toBeGreaterThanOrEqual(8);
  });

  it("靠近下缘时向上收回", () => {
    const pos = clamp(50, 395);
    expect(pos.y).toBeLessThanOrEqual(WIN_H - MENU_HEIGHT - 8);
    expect(pos.y).toBeGreaterThanOrEqual(8);
  });

  it("负坐标钳制到最小边距", () => {
    expect(clamp(-50, -50)).toEqual({ x: 8, y: 8 });
  });

  it("右下角极端坐标不溢出", () => {
    const pos = clamp(1000, 1000);
    expect(pos.x + MENU_WIDTH).toBeLessThanOrEqual(WIN_W - 8);
    expect(pos.y + MENU_HEIGHT).toBeLessThanOrEqual(WIN_H - 8);
  });
});
