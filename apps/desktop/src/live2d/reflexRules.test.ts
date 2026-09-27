/**
 * reflexRules 测试（M-B）：反射事件 → cue 的确定性映射。
 */
import { describe, expect, it } from "vitest";
import { TAP_REPEAT_COUNT, TAP_WINDOW_MS } from "./reflexRules";
import { buildCue, isRepeatTap, toolReflexCues, type ToolReflexStatus } from "./reflexRules";

const NOW = 1_000_000;

describe("buildCue", () => {
  it("static：时长取包络时长", () => {
    const cue = buildCue("celebrate", {
      channel: "body",
      source: "tool",
      resourceType: "static",
      now: NOW,
    });
    expect(cue.durationMs).toBe(1200);
    expect(cue.priority).toBe(60);
    expect(cue.cooldownMs).toBe(10_000);
  });

  it("live2d：固定动作窗口（motion 时长未知）", () => {
    const cue = buildCue("nod", {
      channel: "body",
      source: "reflex",
      resourceType: "live2d",
      now: NOW,
    });
    expect(cue.durationMs).toBeGreaterThanOrEqual(2500);
  });

  it("皮肤声明优先于内置缺省表", () => {
    const cue = buildCue("wave", {
      channel: "body",
      source: "reflex",
      resourceType: "static",
      now: NOW,
      actions: [{ id: "wave", static: { animation: "wave" }, priority: 77, cooldownMs: 999 }],
    });
    expect(cue.priority).toBe(77);
    expect(cue.cooldownMs).toBe(999);
    expect(cue.interruptPolicy).toBe("replace");
  });

  it("face 表情 id 也有缺省优先级（信息性，不抢系统级）", () => {
    const cue = buildCue("happy", {
      channel: "face",
      source: "tool",
      resourceType: "static",
      now: NOW,
    });
    expect(cue.priority).toBe(55);
    expect(cue.priority).toBeLessThan(80);
  });

  it("cueId 唯一（同毫秒多次构造不碰撞）", () => {
    const a = buildCue("nod", {
      channel: "body",
      source: "reflex",
      resourceType: "static",
      now: NOW,
    });
    const b = buildCue("nod", {
      channel: "body",
      source: "reflex",
      resourceType: "static",
      now: NOW,
    });
    expect(a.cueId).not.toBe(b.cueId);
  });
});

describe("isRepeatTap（连续戳）", () => {
  it("窗口内达到阈值 → true", () => {
    const taps = [0, 1, 2].map((i) => NOW - i * 100);
    expect(isRepeatTap(taps, NOW)).toBe(true);
  });

  it("窗口内不足阈值 → false", () => {
    expect(isRepeatTap([NOW - 100, NOW - 200], NOW)).toBe(false);
  });

  it("超出窗口的旧点击不计入", () => {
    const taps = [0, 1, 2].map((i) => NOW - TAP_WINDOW_MS - i * 100);
    expect(isRepeatTap(taps, NOW)).toBe(false);
  });

  it("阈值常量与窗口语义一致", () => {
    const taps = Array.from({ length: TAP_REPEAT_COUNT }, (_, i) => NOW - i);
    expect(isRepeatTap(taps, NOW)).toBe(true);
  });
});

describe("toolReflexCues（工具生命周期反射表）", () => {
  const opts = { resourceType: "static" as const, now: NOW };

  it.each<[ToolReflexStatus, string[], string[]]>([
    ["running", [], ["confused"]],
    ["success", ["celebrate"], ["happy"]],
    ["error", [], ["sad"]],
    ["denied", ["shake_head"], []],
  ])("%s → body %j + face %j", (status, bodyIds, faceIds) => {
    const cues = toolReflexCues(status, opts);
    expect(cues.filter((c) => c.channel === "body").map((c) => c.actionId)).toEqual(bodyIds);
    expect(cues.filter((c) => c.channel === "face").map((c) => c.actionId)).toEqual(faceIds);
    for (const cue of cues) expect(cue.source).toBe("tool");
  });

  it("success 时 body 与 face 并行（两条 cue）", () => {
    const cues = toolReflexCues("success", opts);
    expect(cues).toHaveLength(2);
    expect(new Set(cues.map((c) => c.channel))).toEqual(new Set(["body", "face"]));
  });
});
