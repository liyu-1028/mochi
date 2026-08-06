/**
 * resolveBubbleSide 纯函数测试：气泡去屏幕空间更充足的一侧。
 */
import { describe, expect, it } from "vitest";
import { resolveBubbleSide } from "./useBubbleSide";

describe("resolveBubbleSide", () => {
  it("窗口靠屏幕左半 → 气泡在头部右侧", () => {
    expect(resolveBubbleSide(0, 320, 1440)).toBe("right");
  });

  it("窗口靠屏幕右半 → 气泡在头部左侧", () => {
    expect(resolveBubbleSide(1200, 320, 1440)).toBe("left");
  });

  it("窗口正中（中心恰为屏幕中线）→ 约定归左半、气泡右侧", () => {
    expect(resolveBubbleSide(560, 320, 1440)).toBe("right");
  });
});
