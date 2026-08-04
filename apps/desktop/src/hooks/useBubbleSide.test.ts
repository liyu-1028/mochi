import { describe, expect, it } from "vitest";
import { resolveBubbleSide } from "./useBubbleSide";

describe("resolveBubbleSide（1440px 屏，窗口宽 320）", () => {
  it("窗口贴近屏幕左缘（左侧空间不够）→ 气泡在头部右侧", () => {
    expect(resolveBubbleSide(0, 320, 1440)).toBe("right");
    expect(resolveBubbleSide(300, 320, 1440)).toBe("right");
  });

  it("窗口贴近屏幕右缘（右侧空间不够）→ 气泡在头部左侧", () => {
    expect(resolveBubbleSide(800, 320, 1440)).toBe("left");
    expect(resolveBubbleSide(1120, 320, 1440)).toBe("left");
  });

  it("角色恰好在屏幕中轴线 → 约定取右侧（边界稳定）", () => {
    // charCenterX = 560 + 160 = 720 = screenWidth / 2
    expect(resolveBubbleSide(560, 320, 1440)).toBe("right");
  });
});
