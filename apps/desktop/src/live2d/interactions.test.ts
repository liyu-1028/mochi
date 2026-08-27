/**
 * interactions 纯函数测试（2.4：分区匹配优先级、包络边界、衰减）。
 */
import { describe, expect, it } from "vitest";
import { bodyWiggleAngle, headPatAngleZ, headPatEnvelope, reactionFor } from "./interactions";

describe("reactionFor", () => {
  it("命中 Head（大小写不敏感）", () => {
    expect(reactionFor(["Head"])).toBe("head");
    expect(reactionFor(["hitareaHEAD"])).toBe("head");
  });

  it("命中 Body", () => {
    expect(reactionFor(["Body"])).toBe("body");
    expect(reactionFor(["my-body"])).toBe("body");
  });

  it("Head 优先于 Body（同帧双区命中取摸头）", () => {
    expect(reactionFor(["Body", "Head"])).toBe("head");
  });

  it("空命中/未知分区为 null（静态皮肤路径不产生反应）", () => {
    expect(reactionFor([])).toBeNull();
    expect(reactionFor(["face"])).toBeNull();
  });
});

describe("headPatEnvelope", () => {
  it("头尾平滑归零，中段峰值", () => {
    expect(headPatEnvelope(0)).toBeCloseTo(0);
    expect(headPatEnvelope(600)).toBeCloseTo(1);
    expect(headPatEnvelope(1200)).toBe(0);
  });

  it("超时/负值钳 0", () => {
    expect(headPatEnvelope(1201)).toBe(0);
    expect(headPatEnvelope(-5)).toBe(0);
  });
});

describe("headPatAngleZ", () => {
  it("包络内非零且受限，界外归零", () => {
    expect(headPatAngleZ(300)).not.toBe(0);
    expect(Math.abs(headPatAngleZ(300))).toBeLessThanOrEqual(6);
    expect(headPatAngleZ(1300)).toBe(0);
  });
});

describe("bodyWiggleAngle", () => {
  it("正负交替衰减，峰值受限", () => {
    const angles = [0, 112, 225, 337, 450, 900].map((t) => bodyWiggleAngle(t));
    expect(angles[0]).toBe(0);
    // 前半段存在正负符号交替（震荡）
    const signs = angles.slice(1, 5).map(Math.sign);
    expect(new Set(signs).size).toBeGreaterThan(1);
    expect(angles.every((a) => Math.abs(a) <= 4.001)).toBe(true);
    expect(bodyWiggleAngle(900)).toBe(0);
  });
});
