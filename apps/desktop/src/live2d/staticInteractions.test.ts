/**
 * staticInteractions 纯函数测试：追鼠标侧倾方向/幅度 + 点击果冻弹跳包络。
 */
import { describe, expect, it } from "vitest";
import { CLICK_BOUNCE_MS, clickBounce, gazeLean, LEAN_DX, LEAN_ROT } from "./staticInteractions";

describe("gazeLean", () => {
  it("光标在右侧：右移 + 右倾（正旋转）", () => {
    const lean = gazeLean(0.5, 0);
    expect(lean.dx).toBeCloseTo(0.5 * LEAN_DX, 5);
    expect(lean.rotation).toBeCloseTo(0.5 * LEAN_ROT, 5);
    expect(lean.dy).toBe(0);
  });

  it("光标在上方（gy 向上为正）：微上移（dy 为负）", () => {
    const lean = gazeLean(0, 0.5);
    expect(lean.dy).toBeLessThan(0);
    expect(lean.dx).toBe(0);
    expect(lean.rotation).toBe(0);
  });

  it("中心归零：无侧倾", () => {
    expect(gazeLean(0, 0)).toEqual({ dx: 0, dy: 0, rotation: 0 });
  });
});

describe("clickBounce", () => {
  it("点击瞬间立即压扁（无预热）：sy<1 且横向变宽补偿", () => {
    const b = clickBounce(0)!;
    expect(b.sy).toBeLessThan(1);
    expect(b.sx).toBeGreaterThan(1);
    expect(b.hop).toBeCloseTo(0, 5);
  });

  it("中段上跳（hop 为负）、纵向幅度受限", () => {
    const b = clickBounce(CLICK_BOUNCE_MS / 2)!;
    expect(b.hop).toBeLessThan(0);
    expect(Math.abs(b.sy - 1)).toBeLessThan(0.2);
  });

  it("超时返回 null（反应结束，消费方回落基准变换）", () => {
    expect(clickBounce(CLICK_BOUNCE_MS)).toBeNull();
    expect(clickBounce(CLICK_BOUNCE_MS + 1)).toBeNull();
    expect(clickBounce(-1)).toBeNull();
  });

  it("尾段收敛回 1（阻尼衰减，不突兀截断）", () => {
    const b = clickBounce(CLICK_BOUNCE_MS - 30)!;
    expect(Math.abs(b.sy - 1)).toBeLessThan(0.03);
    expect(Math.abs(b.sx - 1)).toBeLessThan(0.03);
  });
});
