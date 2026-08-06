/**
 * 静态皮肤驱动纯函数测试：computeStaticTransform 六状态 × 参数形状。
 */
import { describe, expect, it } from "vitest";
import {
  STATIC_ANIM_PARAMS,
  computeStaticTransform,
  type StaticAnimationPlan,
} from "./staticDriver";

const OFF: StaticAnimationPlan = {
  float: false,
  breathe: false,
  sway: false,
  talking: false,
  sleeping: false,
  error: false,
  emotionScale: 1,
};

describe("computeStaticTransform", () => {
  it("全关计划 = 恒等变换", () => {
    const tr = computeStaticTransform(OFF, 1.234);
    expect(tr).toEqual({ dx: 0, dy: 0, rotation: 0, scale: 1, tint: 0xffffff });
  });

  it("漂浮：振幅封顶 floatAmp，周期 1/0.8s", () => {
    const p = STATIC_ANIM_PARAMS;
    const peak = computeStaticTransform({ ...OFF, float: true }, 1 / (4 * p.floatFreq));
    expect(peak.dy).toBeCloseTo(p.floatAmp, 5);
    const any = computeStaticTransform({ ...OFF, float: true }, 0.137);
    expect(Math.abs(any.dy)).toBeLessThanOrEqual(p.floatAmp + 1e-9);
  });

  it("呼吸：缩放微幅（≤1%）围绕 1", () => {
    const p = STATIC_ANIM_PARAMS;
    const peak = computeStaticTransform({ ...OFF, breathe: true }, 1 / (4 * p.breatheFreq));
    expect(peak.scale).toBeCloseTo(1 + p.breatheAmp, 5);
  });

  it("摇摆：微旋 ≤0.8° 量级", () => {
    const p = STATIC_ANIM_PARAMS;
    const peak = computeStaticTransform({ ...OFF, sway: true }, 1 / (4 * p.swayFreq));
    expect(peak.rotation).toBeCloseTo(p.swayAmp, 5);
    expect(p.swayAmp).toBeLessThan((1 * Math.PI) / 180);
  });

  it("说话：在情绪缩放上叠加微脉冲", () => {
    const p = STATIC_ANIM_PARAMS;
    const peak = computeStaticTransform(
      { ...OFF, talking: true, emotionScale: 1.05 },
      1 / (4 * p.talkFreq),
    );
    expect(peak.scale).toBeCloseTo(1.05 * (1 + p.talkAmp), 5);
  });

  it("sleeping：灰度 + 下移", () => {
    const tr = computeStaticTransform({ ...OFF, sleeping: true }, 0.5);
    expect(tr.tint).toBe(STATIC_ANIM_PARAMS.sleepTint);
    expect(tr.dy).toBeGreaterThanOrEqual(STATIC_ANIM_PARAMS.sleepDy - STATIC_ANIM_PARAMS.floatAmp);
  });

  it("error：水平抖动且不超过振幅", () => {
    const p = STATIC_ANIM_PARAMS;
    const tr = computeStaticTransform({ ...OFF, error: true }, 1 / (4 * p.errorFreq));
    expect(tr.dx).toBeCloseTo(p.errorAmp, 5);
  });

  it("三轴频率非整数倍（防叠加峰）", () => {
    const p = STATIC_ANIM_PARAMS;
    const r1 = p.floatFreq / p.breatheFreq;
    const r2 = p.breatheFreq / p.swayFreq;
    expect(Number.isInteger(r1)).toBe(false);
    expect(Number.isInteger(r2)).toBe(false);
  });
});
