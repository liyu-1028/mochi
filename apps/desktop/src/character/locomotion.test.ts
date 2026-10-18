import { describe, expect, it } from "vitest";
import type { LocomotionActionId } from "@mochi/protocol";
import {
  LOCOMOTION_STAY_MS,
  approachLerp,
  locomotionPose,
  locomotionTransform,
} from "./locomotion";

/** 标准舞台：活动区 800×280，模型宽高比 0.7（角色显示宽 ≈196） */
const W = 800;
const H = 280;
const ASPECT = 0.7;
const NEUTRAL_POSE = {
  dx: 0,
  dy: 0,
  scale: 1,
  bodyZ: 0,
  headZ: 0,
  bodyY: 0,
  headY: 0,
};

describe("locomotionPose（容器联动位置指令，I3/M-H）", () => {
  it("内部 null 状态回到原位：零位移、零姿态", () => {
    expect(locomotionPose(null, W, H, ASPECT)).toEqual(NEUTRAL_POSE);
  });

  it.each(["peek_dock", "lean_edge", "lean_bubble", "peek_out", "come_back", "not_a_position"])(
    "未注册或已删除的位置 %s 回落到中性姿态",
    (id) => {
      expect(locomotionPose(id as LocomotionActionId, W, H, ASPECT)).toEqual(NEUTRAL_POSE);
    },
  );
});

describe("approachLerp（姿态指数趋近）", () => {
  it("向目标靠近且不越过；距离足够近时吸附到目标", () => {
    expect(approachLerp(0, 10)).toBeGreaterThan(0);
    expect(approachLerp(0, 10)).toBeLessThan(10);
    expect(approachLerp(9.999, 10)).toBe(10);
    expect(approachLerp(5, 5)).toBe(5);
  });
});

describe("locomotionTransform / LOCOMOTION_STAY_MS", () => {
  it("transform 字符串含位移与缩放", () => {
    const s = locomotionTransform({
      dx: 100,
      dy: -8,
      scale: 1.04,
      bodyZ: 0,
      headZ: 0,
      bodyY: 0,
      headY: 0,
    });
    expect(s).toContain("translate(100.0px, -8.0px)");
    expect(s).toContain("scale(1.04)");
  });

  it("停留时长为 14s（超时自动回位）", () => {
    expect(LOCOMOTION_STAY_MS).toBe(14_000);
  });
});
