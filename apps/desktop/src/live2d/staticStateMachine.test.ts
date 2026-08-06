/**
 * 静态皮肤状态机纯函数测试：六状态 × 缺省兜底 × 情绪缩放。
 */
import { describe, expect, it } from "vitest";
import { resolveStaticAnimation } from "./staticStateMachine";

const SKIN = {
  animation: {
    idle: { float: true, breathe: true },
    working: { sway: true },
  },
  emotionMapping: { happy: { scale: 1.05, tint: null } },
};

describe("resolveStaticAnimation", () => {
  it("状态动画开关取自清单", () => {
    const idle = resolveStaticAnimation("idle", null, SKIN);
    expect(idle).toMatchObject({ float: true, breathe: true, sway: false });

    const working = resolveStaticAnimation("working", null, SKIN);
    expect(working).toMatchObject({ float: false, sway: true });
  });

  it("状态标志严格对应", () => {
    expect(resolveStaticAnimation("talking", null, SKIN).talking).toBe(true);
    expect(resolveStaticAnimation("sleeping", null, SKIN).sleeping).toBe(true);
    expect(resolveStaticAnimation("error", null, SKIN).error).toBe(true);
    expect(resolveStaticAnimation("idle", null, SKIN)).toMatchObject({
      talking: false,
      sleeping: false,
      error: false,
    });
  });

  it("清单缺 animation：全关兜底不崩", () => {
    const plan = resolveStaticAnimation("idle", null, {});
    expect(plan).toMatchObject({ float: false, breathe: false, sway: false, emotionScale: 1 });
  });

  it("情绪缩放取 emotionMapping，缺省 1", () => {
    expect(resolveStaticAnimation("idle", "happy", SKIN).emotionScale).toBe(1.05);
    expect(resolveStaticAnimation("idle", "sad", SKIN).emotionScale).toBe(1);
    expect(resolveStaticAnimation("idle", null, SKIN).emotionScale).toBe(1);
  });
});
