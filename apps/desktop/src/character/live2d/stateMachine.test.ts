/**
 * 动画状态机单测（功能清单 2.2）。
 * vitest node 环境：纯函数，不依赖 DOM/PIXI。
 */
import { CHARACTER_STATES, type CharacterState, type Emotion } from "@mochi/protocol";
import { describe, expect, it } from "vitest";
import {
  BODY_ACTION_ENVELOPES,
  EMOTION_PRESETS,
  HIYORI_PROFILE,
  resolveAnimation,
  STATE_RULES,
  thinkingPoseParams,
  DOZE_DURATION_MS,
  WINK_DURATION_MS,
  WINK_ENVELOPE,
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

  it("仅 thinking 启用思考姿态（歪头 + 缓慢摆动）", () => {
    expect(resolveAnimation("thinking", null, HIYORI_PROFILE).thinkingPose).toBe(true);
    for (const state of CHARACTER_STATES.filter((s) => s !== "thinking")) {
      expect(resolveAnimation(state, null, HIYORI_PROFILE).thinkingPose).toBe(false);
    }
  });

  it("working 启用持续打字姿态（批次 3 I1），其余状态 bodySway/typing 均关", () => {
    const working = resolveAnimation("working", null, HIYORI_PROFILE);
    expect(working.typing).toBe(true);
    expect(working.bodySway).toBe(false); // 打字姿态自带身体前倾，与微晃互斥
    for (const state of CHARACTER_STATES.filter((s) => s !== "working")) {
      const plan = resolveAnimation(state, null, HIYORI_PROFILE);
      expect(plan.typing).toBe(false);
      expect(plan.bodySway).toBe(false);
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

  it("模型带 Think 动作组时思考优先选用，其余状态不受影响", () => {
    const profile: ModelProfile = { motionGroups: ["Idle", "Think"], expressions: [] };
    expect(resolveAnimation("thinking", null, profile).motionGroup).toBe("Think");
    expect(resolveAnimation("idle", null, profile).motionGroup).toBe("Idle");
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

  it("thinkingPoseParams：歪头角度在 [9, 19] 内缓慢摆动，低头为负", () => {
    for (const t of [0, 1, 2.7, 5, 100.5]) {
      const pose = thinkingPoseParams(t);
      expect(pose.ParamAngleZ).toBeGreaterThanOrEqual(9);
      expect(pose.ParamAngleZ).toBeLessThanOrEqual(19);
      expect(pose.ParamAngleY).toBeLessThan(0); // 微微低头，与视线上瞟叠加
      expect(Math.abs(pose.ParamBodyAngleZ)).toBeLessThanOrEqual(30);
    }
    // 摆动确实随时间变化（否则姿态僵死）
    expect(thinkingPoseParams(0).ParamAngleZ).not.toBeCloseTo(thinkingPoseParams(2).ParamAngleZ, 1);
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

  it("wink 包络（M-F）：三角形闭眼包络，包络值均在模型安全范围，结束返回 null", () => {
    expect(WINK_ENVELOPE.params(-1)).toBeNull();
    expect(WINK_ENVELOPE.params(WINK_DURATION_MS)).toBeNull();
    const mid = WINK_ENVELOPE.params(WINK_DURATION_MS / 2);
    expect(mid).not.toBeNull();
    expect(mid?.ParamEyeLOpen).toBeCloseTo(0); // 闭合峰值
    const start = WINK_ENVELOPE.params(0);
    expect(start?.ParamEyeLOpen).toBeCloseTo(1); // 睁眼起点
    // BODY_ACTION_ENVELOPES 表与协议词表一致：wink 可查
    expect(BODY_ACTION_ENVELOPES.wink).toBe(WINK_ENVELOPE);
    // 全包络采样：值不越界（组件层 setParam 会再按模型范围钳制）
    for (let t = 0; t < WINK_DURATION_MS; t += 50) {
      const p = WINK_ENVELOPE.params(t);
      expect(p).not.toBeNull();
      for (const [param, value] of Object.entries(p ?? {})) {
        const isAngle = param.startsWith("ParamAngle") || param.startsWith("ParamBody");
        expect(Math.abs(value ?? 0)).toBeLessThanOrEqual(isAngle ? 30 : 1.01);
      }
    }
  });

  it("G1 包络表：pout/laugh/shy_shake/alert/doze 可查、时长/端点/值域正确", () => {
    const durations: Record<string, number> = {
      pout: 900,
      laugh: 1200,
      shy_shake: 1100,
      alert: 800,
      doze: DOZE_DURATION_MS,
    };
    for (const [id, duration] of Object.entries(durations)) {
      const env = BODY_ACTION_ENVELOPES[id];
      expect(env, id).toBeTruthy();
      expect(env!.durationMs, id).toBe(duration);
      expect(env!.params(-1), `${id} 负时间`).toBeNull();
      expect(env!.params(duration), `${id} 恰好到期`).toBeNull();
      expect(env!.params(0), `${id} 起点`).not.toBeNull();
      // 全采样值域：角度/身体类 ≤30，其余（表情/开合/眼球）≤1.01
      for (let t = 0; t < duration; t += 40) {
        const p = env!.params(t);
        expect(p, `${id}@${t}`).not.toBeNull();
        for (const [param, value] of Object.entries(p ?? {})) {
          const isAngle = param.startsWith("ParamAngle") || param.startsWith("ParamBody");
          // alert 有意把睁眼推到 1.3（运行时 setParam 按模型实际上限钳制）
          const isEyeOpen = param === "ParamEyeLOpen" || param === "ParamEyeROpen";
          const limit = isAngle ? 30 : isEyeOpen && id === "alert" ? 1.31 : 1.01;
          expect(Math.abs(value ?? 0), `${id}@${t}:${param}`).toBeLessThanOrEqual(limit);
        }
      }
    }
  });

  it("G1 包络语义：pout 收嘴、laugh 张嘴两拍、shy_shake 脸颊、alert 睁眼放大、doze 闭眼下垂", () => {
    // pout：中段嘴形为负（收拢）
    expect(BODY_ACTION_ENVELOPES.pout!.params(450)?.ParamMouthForm).toBeLessThan(0);
    // laugh：两拍（600ms 周期）——半拍处张开、拍谷闭合，整体包络叠加淡入淡出
    const laughPeak = BODY_ACTION_ENVELOPES.laugh!.params(150)?.ParamMouthOpenY ?? 0;
    const laughValley = BODY_ACTION_ENVELOPES.laugh!.params(300)?.ParamMouthOpenY ?? 0;
    expect(laughPeak).toBeGreaterThan(0.3); // 拍峰（含淡入衰减后仍明显张开）
    expect(laughValley).toBeCloseTo(0, 5); // 拍谷闭合
    // shy_shake：脸颊随时间升起且不超 1
    const shyEarly = BODY_ACTION_ENVELOPES.shy_shake!.params(100)?.ParamCheek ?? 0;
    const shyLate = BODY_ACTION_ENVELOPES.shy_shake!.params(900)?.ParamCheek ?? 0;
    expect(shyLate).toBeGreaterThan(shyEarly);
    expect(shyLate).toBeLessThanOrEqual(1);
    // alert：前 120ms 内头部抬起上升，末端参数回落但不为 null（包络窗口内）
    const alertEarly = BODY_ACTION_ENVELOPES.alert!.params(60)?.ParamAngleY ?? 0;
    expect(alertEarly).toBeGreaterThan(0);
    // doze：中段闭眼（眼开接近 0）+ 头下垂为负
    const dozeMid = BODY_ACTION_ENVELOPES.doze!.params(DOZE_DURATION_MS / 2);
    expect(dozeMid?.ParamEyeLOpen).toBeCloseTo(0, 5);
    expect(dozeMid?.ParamAngleY).toBeLessThan(0);
  });
});
