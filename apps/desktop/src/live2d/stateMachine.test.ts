/**
 * 动画状态机单测（功能清单 2.2）。
 * vitest node 环境：纯函数，不依赖 DOM/PIXI。
 */
import { CHARACTER_STATES, type CharacterState, type Emotion } from "@mochi/protocol";
import { describe, expect, it } from "vitest";
import {
  EMOTION_PRESETS,
  HIYORI_PROFILE,
  resolveAnimation,
  STATE_RULES,
  type ModelProfile,
} from "./stateMachine";

const PROFILE_WITH_EXPRESSIONS: ModelProfile = {
  motionGroups: ["Idle", "Tap"],
  expressions: ["happy", "sad"],
};

describe("resolveAnimation：6 状态基础计划", () => {
  it("每个协议状态都能产出计划且动作组可解", () => {
    for (const state of CHARACTER_STATES) {
      const plan = resolveAnimation(state, null, HIYORI_PROFILE);
      expect(plan.motionGroup).toBe("Idle"); // Hiyori 全部回退到 Idle 组
      expect([30, 60]).toContain(plan.tickerFps);
    }
  });

  it("说话期启用口型驱动，其余状态关闭", () => {
    expect(resolveAnimation("talking", null, HIYORI_PROFILE).mouthEnabled).toBe(true);
    for (const state of CHARACTER_STATES.filter((s) => s !== "talking")) {
      expect(resolveAnimation(state, null, HIYORI_PROFILE).mouthEnabled).toBe(false);
    }
  });

  it("sleeping/error 禁用视线跟随，其余状态启用", () => {
    expect(resolveAnimation("sleeping", null, HIYORI_PROFILE).gazeEnabled).toBe(false);
    expect(resolveAnimation("error", null, HIYORI_PROFILE).gazeEnabled).toBe(false);
    for (const state of ["idle", "talking", "thinking", "working"] as CharacterState[]) {
      expect(resolveAnimation(state, null, HIYORI_PROFILE).gazeEnabled).toBe(true);
    }
  });

  it("思考时视线上瞟（gazeOffsetY > 0），出错时低头（< 0）", () => {
    expect(resolveAnimation("thinking", null, HIYORI_PROFILE).gazeOffsetY).toBeGreaterThan(0);
    expect(resolveAnimation("error", null, HIYORI_PROFILE).gazeOffsetY).toBeLessThan(0);
  });

  it("仅 working 启用身体微晃", () => {
    expect(resolveAnimation("working", null, HIYORI_PROFILE).bodySway).toBe(true);
    for (const state of CHARACTER_STATES.filter((s) => s !== "working")) {
      expect(resolveAnimation(state, null, HIYORI_PROFILE).bodySway).toBe(false);
    }
  });

  it("仅 sleeping 强制闭眼", () => {
    expect(resolveAnimation("sleeping", null, HIYORI_PROFILE).eyesClosed).toBe(true);
    for (const state of CHARACTER_STATES.filter((s) => s !== "sleeping")) {
      expect(resolveAnimation(state, null, HIYORI_PROFILE).eyesClosed).toBe(false);
    }
  });

  it("error/sleeping 用 force 优先级覆盖当前动作", () => {
    expect(resolveAnimation("error", null, HIYORI_PROFILE).motionPriority).toBe("force");
    expect(resolveAnimation("sleeping", null, HIYORI_PROFILE).motionPriority).toBe("force");
    expect(resolveAnimation("idle", null, HIYORI_PROFILE).motionPriority).toBe("idle");
  });
});

describe("resolveAnimation：情绪映射", () => {
  it("emotion=null 落到 neutral 预设", () => {
    const plan = resolveAnimation("idle", null, HIYORI_PROFILE);
    expect(plan.expression).toEqual({ kind: "params", preset: "neutral" });
  });

  it("Hiyori 无 exp3：全部情绪走参数预设分支", () => {
    for (const emotion of Object.keys(EMOTION_PRESETS) as Emotion[]) {
      const plan = resolveAnimation("idle", emotion, HIYORI_PROFILE);
      expect(plan.expression).toEqual({ kind: "params", preset: emotion });
    }
  });

  it("带 exp3 的模型：匹配的情绪走表情文件分支", () => {
    expect(resolveAnimation("idle", "happy", PROFILE_WITH_EXPRESSIONS).expression).toEqual({
      kind: "file",
      name: "happy",
    });
    // 不在 exp3 列表中的情绪仍走参数预设
    expect(resolveAnimation("idle", "angry", PROFILE_WITH_EXPRESSIONS).expression).toEqual({
      kind: "params",
      preset: "angry",
    });
  });

  it("thinking 强制 confused、error 强制 sad（忽略输入情绪）", () => {
    expect(resolveAnimation("thinking", "happy", HIYORI_PROFILE).expression).toEqual({
      kind: "params",
      preset: "confused",
    });
    expect(resolveAnimation("error", "happy", HIYORI_PROFILE).expression).toEqual({
      kind: "params",
      preset: "sad",
    });
  });

  it("其余状态尊重输入情绪", () => {
    expect(resolveAnimation("talking", "happy", HIYORI_PROFILE).expression).toEqual({
      kind: "params",
      preset: "happy",
    });
  });
});

describe("resolveAnimation：模型能力回退", () => {
  it("偏好组缺失时回退到模型第一个可用组", () => {
    const profile: ModelProfile = { motionGroups: ["Tap", "Flick"], expressions: [] };
    expect(resolveAnimation("idle", null, profile).motionGroup).toBe("Tap");
  });

  it("模型无任何动作组时返回 null（组件跳过动作切换）", () => {
    const profile: ModelProfile = { motionGroups: [], expressions: [] };
    expect(resolveAnimation("idle", null, profile).motionGroup).toBeNull();
  });
});

describe("配置一致性", () => {
  it("STATE_RULES 覆盖协议全部 6 状态", () => {
    expect(Object.keys(STATE_RULES).sort()).toEqual([...CHARACTER_STATES].sort());
  });

  it("情绪预设值均在归一化范围 [-1, 1]（角度类例外需组件层换算）", () => {
    for (const preset of Object.values(EMOTION_PRESETS)) {
      for (const [param, value] of Object.entries(preset)) {
        const isAngle = param.startsWith("ParamAngle");
        const limit = isAngle ? 30 : 1; // 角度参数范围更大
        expect(Math.abs(value)).toBeLessThanOrEqual(limit);
      }
    }
  });
});
