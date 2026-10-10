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
const CHAR_W = H * ASPECT; // 196

describe("locomotionPose（容器联动位置指令，I3/M-H）", () => {
  it("come_back 回到原位：零位移、零姿态", () => {
    const pose = locomotionPose("come_back", W, H, ASPECT);
    expect(pose.dx).toBe(0);
    expect(pose.dy).toBe(0);
    expect(pose.scale).toBe(1);
    expect(pose.bodyZ).toBe(0);
    expect(pose.headZ).toBe(0);
  });

  it("靠墙（lean_edge）：贴到容器右缘，身体向墙倾斜", () => {
    const pose = locomotionPose("lean_edge", W, H, ASPECT);
    const margin = (W - CHAR_W) / 2; // 302
    expect(pose.dx).toBeCloseTo(margin - 2, 5);
    expect(pose.bodyZ).toBeGreaterThan(0); // 向右（墙侧）倾斜
    expect(pose.scale).toBe(1);
  });

  it("探头（peek_out）：向左移出半个身位（窗口外不可见 → 只探出半身）", () => {
    const pose = locomotionPose("peek_out", W, H, ASPECT);
    const margin = (W - CHAR_W) / 2;
    expect(pose.dx).toBeLessThan(-margin); // 超出左缘
    expect(pose.dx).toBeGreaterThan(-(margin + CHAR_W)); // 未完全出窗
    expect(pose.bodyZ).toBeLessThan(0);
  });

  it("趴输入框（peek_dock）：下移压近 + 微放大 + 前倾低头", () => {
    const pose = locomotionPose("peek_dock", W, H, ASPECT);
    expect(pose.dy).toBeGreaterThan(0);
    expect(pose.scale).toBeGreaterThan(1);
    expect(pose.bodyY).toBeLessThan(0); // 前倾
    expect(pose.headY).toBeLessThan(0); // 低头
  });

  it("靠气泡（lean_bubble）：上提侧靠，头偏向气泡侧", () => {
    const pose = locomotionPose("lean_bubble", W, H, ASPECT);
    expect(pose.dy).toBeLessThan(0);
    expect(pose.headZ).toBeLessThan(0);
  });

  it("未知位置等同 come_back（防御：白名单外 id 不产生位移）", () => {
    const pose = locomotionPose("not_a_position" as LocomotionActionId, W, H, ASPECT);
    expect(pose.dx).toBe(0);
    expect(pose.dy).toBe(0);
  });

  it("窗口未扩容（余量 ≤0）：所有位置都不动（窄角色/兜底布局零回归）", () => {
    const narrow = 150; // 余量 = (150-196)/2 < 0
    for (const id of ["lean_edge", "peek_out", "peek_dock", "lean_bubble"] as const) {
      expect(locomotionPose(id, narrow, H, ASPECT).dx).toBe(0);
      expect(locomotionPose(id, narrow, H, ASPECT).dy).toBe(0);
    }
  });
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
