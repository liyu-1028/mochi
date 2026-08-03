/**
 * 视线跟随单测（功能清单 2.4）。纯函数，node 环境。
 */
import { describe, expect, it } from "vitest";
import { GAZE_SENSITIVITY, lerpGaze, normalizeGaze, type StageRect } from "./gaze";

const RECT: StageRect = { left: 0, top: 0, width: 420, height: 260 };

describe("normalizeGaze：坐标归一化", () => {
  it("舞台中心 → (0, 0)", () => {
    expect(normalizeGaze(210, 130, RECT)).toEqual({ x: 0, y: 0 });
  });

  it("右侧边缘 → x 为灵敏度上限；屏幕下方 → y 为负（Live2D Y 向上）", () => {
    const right = normalizeGaze(420, 130, RECT);
    expect(right.x).toBeCloseTo(GAZE_SENSITIVITY);
    const bottom = normalizeGaze(210, 260, RECT);
    expect(bottom.y).toBeCloseTo(-GAZE_SENSITIVITY);
  });

  it("超出舞台的坐标被钳制（不贴边溢出）", () => {
    const far = normalizeGaze(10000, -10000, RECT);
    expect(far.x).toBeLessThanOrEqual(GAZE_SENSITIVITY);
    expect(far.y).toBeLessThanOrEqual(GAZE_SENSITIVITY);
  });

  it("退化矩形（零尺寸）返回原点", () => {
    expect(normalizeGaze(10, 10, { left: 0, top: 0, width: 0, height: 0 })).toEqual({
      x: 0,
      y: 0,
    });
  });
});

describe("lerpGaze：平滑逼近", () => {
  it("向目标逼近但不跳变", () => {
    const next = lerpGaze({ x: 0, y: 0 }, { x: 1, y: 1 });
    expect(next.x).toBeGreaterThan(0);
    expect(next.x).toBeLessThan(1);
  });

  it("多帧后收敛到目标", () => {
    let cur = { x: 0, y: 0 };
    for (let i = 0; i < 60; i++) cur = lerpGaze(cur, { x: 0.6, y: -0.3 });
    expect(cur.x).toBeCloseTo(0.6, 2);
    expect(cur.y).toBeCloseTo(-0.3, 2);
  });
});
