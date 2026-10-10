/**
 * reflexRules 测试（M-B）：反射事件 → cue 的确定性映射。
 */
import { describe, expect, it } from "vitest";
import { pickIdleAction, TAP_REPEAT_COUNT, TAP_WINDOW_MS } from "./reflexRules";
import {
  buildCue,
  isRepeatTap,
  LIVE2D_ACTION_MS,
  toolReflexCues,
  type ToolReflexStatus,
} from "./reflexRules";
import { DEFAULT_LIVE2D_ACTIONS } from "./live2d/actionRegistry";

const NOW = 1_000_000;

describe("buildCue", () => {
  it("one-shot 时长为固定动作窗口（motion 实际时长未知）", () => {
    const cue = buildCue("nod", {
      channel: "body",
      source: "reflex",
      now: NOW,
    });
    expect(cue.durationMs).toBeGreaterThanOrEqual(2500);
  });

  it("内置缺省表：celebrate 优先级/冷却", () => {
    const cue = buildCue("celebrate", {
      channel: "body",
      source: "tool",
      now: NOW,
    });
    expect(cue.priority).toBe(60);
    expect(cue.cooldownMs).toBe(10_000);
  });

  it("皮肤声明优先于内置缺省表", () => {
    const cue = buildCue("wave", {
      channel: "body",
      source: "reflex",
      now: NOW,
      actions: [{ id: "wave", live2d: { motionGroups: ["Tap"] }, priority: 77, cooldownMs: 999 }],
    });
    expect(cue.priority).toBe(77);
    expect(cue.cooldownMs).toBe(999);
    expect(cue.interruptPolicy).toBe("replace");
  });

  it("skin 条目 durationMs 作占位窗口（v3，G3）：包络动作不再空占 2500ms", () => {
    const cue = buildCue("bounce", {
      channel: "body",
      source: "reflex",
      now: NOW,
      actions: [
        {
          id: "bounce",
          live2d: {
            paramEnvelope: {
              durationMs: 900,
              keyframes: [
                {
                  param: "P",
                  points: [
                    [0, 0],
                    [900, 0],
                  ],
                },
              ],
            },
          },
          durationMs: 900,
        },
      ],
    });
    expect(cue.durationMs).toBe(900);
    // 无 durationMs 声明时回退通用窗口
    const cueDefault = buildCue("bounce", {
      channel: "body",
      source: "reflex",
      now: NOW,
      actions: [{ id: "bounce", live2d: { motionGroups: ["Tap"] } }],
    });
    expect(cueDefault.durationMs).toBe(LIVE2D_ACTION_MS);
  });

  it("face 表情 id 也有缺省优先级（信息性，不抢系统级）", () => {
    const cue = buildCue("happy", {
      channel: "face",
      source: "tool",
      now: NOW,
    });
    expect(cue.priority).toBe(55);
    expect(cue.priority).toBeLessThan(80);
  });

  it("cueId 唯一（同毫秒多次构造不碰撞）", () => {
    const a = buildCue("nod", {
      channel: "body",
      source: "reflex",
      now: NOW,
    });
    const b = buildCue("nod", {
      channel: "body",
      source: "reflex",
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

describe("toolReflexCues（工具生命周期反射表，对齐 rollout plan B3）", () => {
  const opts = { now: NOW };

  it.each<[ToolReflexStatus, string[], string[]]>([
    ["running", ["think"], []],
    ["success", ["celebrate"], ["happy"]],
    ["error", [], ["worried"]],
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

describe("默认值一致性（消除漂移）", () => {
  it("reflexRules DEFAULTS 基线与 DEFAULT_LIVE2D_ACTIONS 声明一致", () => {
    for (const action of DEFAULT_LIVE2D_ACTIONS) {
      const cue = buildCue(action.id, {
        channel: "body",
        source: "reflex",
        now: NOW,
      });
      expect(cue.priority, action.id).toBe(action.priority);
      expect(cue.cooldownMs, action.id).toBe(action.cooldownMs ?? 0);
    }
  });
});

// ---- 闲置轮换池（批次 3 I2）----

describe("pickIdleAction（闲置轮换池渐进权重）", () => {
  const pick = (idleMs: number, rand: number) => pickIdleAction(idleMs, rand);

  it("刚进入 idle（<评估间隔）一律安静", () => {
    expect(pick(0, 0)).toBeNull();
    expect(pick(24_999, 0)).toBeNull();
  });

  it("短闲置（<2min）：只会在 look_around/idle_hum 中小概率触发", () => {
    expect(pick(60_000, 0)).toBe("look_around"); // rand=0 → 第一项
    expect(pick(60_000, 0.25)).toBe("idle_hum");
    expect(pick(60_000, 0.5)).toBeNull(); // 0.25+0.1=0.35 之外静默
    expect(pick(60_000, 0.9)).toBeNull();
    // 短档绝不出现 doze/stretch（久置专属）
    for (let r = 0; r < 1; r += 0.01) {
      const id = pick(60_000, r);
      expect(id === null || id === "look_around" || id === "idle_hum").toBe(true);
    }
  });

  it("久置（>5min）：doze 权重最高（rand=0 直接打盹），档内权重合计 1.0 恒触发", () => {
    expect(pick(360_000, 0)).toBe("doze");
    expect(pick(360_000, 0.5)).toBe("stretch");
    expect(pick(360_000, 0.75)).toBe("look_around");
    expect(pick(360_000, 0.85)).toBe("idle_hum");
  });

  it("mid 档（2–5min）无 doze", () => {
    for (let r = 0; r < 1; r += 0.01) {
      expect(pick(200_000, r)).not.toBe("doze");
    }
  });
});
