/**
 * idleBehaviors 纯函数测试：四个动作的包络边界、时长与「不打扰」幅度约束。
 */
import { describe, expect, it } from "vitest";
import {
  IDLE_ACTIONS,
  IDLE_MAX_GAP_MS,
  IDLE_MIN_GAP_MS,
  nextIdleGap,
  pickIdleAction,
} from "./idleBehaviors";

/** 采样整个时程，断言所有帧的幅度约束（不发声/不溢窗的产品约束）。 */
function sampleAll(
  apply: (
    ms: number,
  ) => { dx: number; dy: number; rotation: number; sx: number; sy: number } | null,
  durationMs: number,
) {
  const frames = [];
  for (let ms = 0; ms < durationMs; ms += 50) frames.push(apply(ms)!);
  return frames;
}

describe("IDLE_ACTIONS 包络", () => {
  it("四个动作齐备（张望/伸懒腰/打盹/扭摆）", () => {
    expect(IDLE_ACTIONS.map((a) => a.id)).toEqual(["lookAround", "stretch", "doze", "wiggle"]);
  });

  it("超时返回 null（动作自然结束）", () => {
    for (const a of IDLE_ACTIONS) {
      expect(a.apply(a.durationMs)).toBeNull();
      expect(a.apply(a.durationMs + 1)).toBeNull();
      expect(a.apply(-1)).toBeNull();
    }
  });

  it("幅度约束：位移 ≤8px、旋转 ≤0.12rad、缩放 ∈ [0.9, 1.15]（不打扰用户）", () => {
    for (const a of IDLE_ACTIONS) {
      for (const f of sampleAll(a.apply, a.durationMs)) {
        expect(Math.abs(f.dx)).toBeLessThanOrEqual(8);
        expect(Math.abs(f.dy)).toBeLessThanOrEqual(8);
        expect(Math.abs(f.rotation)).toBeLessThanOrEqual(0.12);
        expect(f.sx).toBeGreaterThanOrEqual(0.9);
        expect(f.sx).toBeLessThanOrEqual(1.15);
        expect(f.sy).toBeGreaterThanOrEqual(0.9);
        expect(f.sy).toBeLessThanOrEqual(1.15);
      }
    }
  });

  it("张望：扫过左右两侧（dx 变号）", () => {
    const dxs = sampleAll(IDLE_ACTIONS[0].apply, 2600).map((f) => f.dx);
    expect(Math.max(...dxs)).toBeGreaterThan(3);
    expect(Math.min(...dxs)).toBeLessThan(-3);
  });

  it("伸懒腰：中段纵向拉高（sy > 1）横向收窄（sx < 1）", () => {
    const mid = IDLE_ACTIONS[1].apply(900)!;
    expect(mid.sy).toBeGreaterThan(1.03);
    expect(mid.sx).toBeLessThan(1);
  });

  it("打盹：中段垂头（dy > 0），结尾收敛回零附近（不突兀截断）", () => {
    const mid = IDLE_ACTIONS[2].apply(2000)!;
    expect(mid.dy).toBeGreaterThan(1);
    const end = IDLE_ACTIONS[2].apply(4150)!;
    expect(Math.abs(end.dy)).toBeLessThan(0.5);
    expect(Math.abs(end.rotation)).toBeLessThan(0.08);
  });

  it("扭摆：有摆动且衰减（峰值在前半程）", () => {
    const first = Math.max(
      ...sampleAll(IDLE_ACTIONS[3].apply, 600).map((f) => Math.abs(f.rotation)),
    );
    const last = Math.max(
      ...sampleAll(IDLE_ACTIONS[3].apply, 1200)
        .slice(-6)
        .map((f) => Math.abs(f.rotation)),
    );
    expect(first).toBeGreaterThan(0.03);
    expect(first).toBeGreaterThan(last);
  });
});

describe("调度辅助", () => {
  it("nextIdleGap 落在区间内", () => {
    for (let i = 0; i < 50; i += 1) {
      const gap = nextIdleGap();
      expect(gap).toBeGreaterThanOrEqual(IDLE_MIN_GAP_MS);
      expect(gap).toBeLessThanOrEqual(IDLE_MAX_GAP_MS);
    }
  });

  it("pickIdleAction 排除上一个动作（不连续重复）", () => {
    for (let i = 0; i < 20; i += 1) {
      expect(pickIdleAction("doze").id).not.toBe("doze");
    }
    expect(IDLE_ACTIONS).toContain(pickIdleAction());
  });
});
