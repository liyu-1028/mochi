/**
 * actionDirector 测试（M-B 验收）：
 * - face+body 并行（body one-shot 不清 face）
 * - 打断守卫：低优先级不打断 talking/dragging，系统级可打断 idle
 * - 单槽队列：替换/挤掉/TTL 过期不补演
 * - 冷却、省电、TTL、非法输入
 * - 反射路径纯逻辑耗时 <16ms/帧
 */
import { describe, expect, it } from "vitest";
import type { CharacterState } from "@mochi/protocol";
import {
  BUSY_GUARD_PRIORITY,
  createDirectorState,
  submitCue,
  tickDirector,
  activeOn,
  type DirectorContext,
  type DirectorCue,
} from "./actionDirector";

const T0 = 1_000_000;

function ctx(overrides: Partial<DirectorContext> = {}): DirectorContext {
  return {
    state: "idle",
    speaking: false,
    dragging: false,
    decorationsPaused: false,
    ...overrides,
  };
}

function cue(overrides: Partial<DirectorCue> = {}): DirectorCue {
  return {
    cueId: "c1",
    actionId: "nod",
    channel: "body",
    priority: 50,
    interruptPolicy: "replace",
    ttlMs: 2000,
    cooldownMs: 0,
    durationMs: 1000,
    source: "reflex",
    createdAt: T0,
    ...overrides,
  };
}

describe("通道并行（AIRI 教训回归）", () => {
  it("face 与 body 同时活跃：body one-shot 全程不清 face", () => {
    const state = createDirectorState();
    const face = cue({ cueId: "f1", actionId: "happy_face", channel: "face", durationMs: 5000 });
    const body = cue({ cueId: "b1", actionId: "nod", channel: "body", durationMs: 1000 });
    expect(submitCue(state, face, ctx(), T0).accepted).toBe(true);
    expect(submitCue(state, body, ctx(), T0).accepted).toBe(true);
    // body 播放中段：face 仍活跃
    tickDirector(state, ctx(), T0 + 500);
    expect(activeOn(state, "face")?.cue.actionId).toBe("happy_face");
    expect(activeOn(state, "body")?.cue.actionId).toBe("nod");
    // body 结束后：face 未受影响
    tickDirector(state, ctx(), T0 + 1000);
    expect(activeOn(state, "body")).toBeNull();
    expect(activeOn(state, "face")?.cue.actionId).toBe("happy_face");
  });
});

describe("打断守卫（低优先级不打断交互）", () => {
  const busyCases: Array<[string, DirectorContext]> = [
    ["speaking", ctx({ speaking: true })],
    ["talking state", ctx({ state: "talking" })],
    ["dragging", ctx({ dragging: true })],
  ];

  for (const [name, context] of busyCases) {
    it(`${name}：低优先级被拒（busy_guard）`, () => {
      const state = createDirectorState();
      const verdict = submitCue(state, cue({ priority: 60 }), context, T0);
      expect(verdict).toEqual({ accepted: false, reason: "busy_guard" });
    });

    it(`${name}：系统级（>=80）放行`, () => {
      const state = createDirectorState();
      const verdict = submitCue(
        state,
        cue({ priority: BUSY_GUARD_PRIORITY, actionId: "surprised" }),
        context,
        T0,
      );
      expect(verdict.accepted).toBe(true);
    });
  }

  it("idle：低优先级正常执行", () => {
    const state = createDirectorState();
    const verdict = submitCue(state, cue(), ctx(), T0);
    expect(verdict).toEqual({ accepted: true, channel: "body", startImmediately: true });
  });
});

describe("打断与队列", () => {
  it("通道空闲立即开始；同一通道第二个 cue 进单槽队列", () => {
    const state = createDirectorState();
    expect(submitCue(state, cue({ cueId: "1" }), ctx(), T0).accepted).toBe(true);
    const second = submitCue(state, cue({ cueId: "2", actionId: "wave" }), ctx(), T0 + 10);
    expect(second).toEqual({ accepted: true, channel: "body", startImmediately: false });
    expect(activeOn(state, "body")?.cue.cueId).toBe("1");
  });

  it("高优先级 replace 打断正在执行的 one-shot", () => {
    const state = createDirectorState();
    submitCue(state, cue({ cueId: "low", priority: 30, durationMs: 5000 }), ctx(), T0);
    const verdict = submitCue(
      state,
      cue({ cueId: "high", priority: 70, actionId: "celebrate" }),
      ctx(),
      T0 + 100,
    );
    expect(verdict).toEqual({ accepted: true, channel: "body", startImmediately: true });
    expect(activeOn(state, "body")?.cue.actionId).toBe("celebrate");
  });

  it("ignore 策略：通道忙时直接丢弃", () => {
    const state = createDirectorState();
    submitCue(state, cue({ cueId: "1" }), ctx(), T0);
    const verdict = submitCue(
      state,
      cue({ cueId: "2", actionId: "wave", interruptPolicy: "ignore" }),
      ctx(),
      T0 + 10,
    );
    expect(verdict).toEqual({ accepted: false, reason: "ignored" });
  });

  it("单槽队列：同优先级替换队首；低优先级挤不掉（queue_full）；结束后提升队首", () => {
    const state = createDirectorState();
    submitCue(state, cue({ cueId: "running", durationMs: 5000 }), ctx(), T0);
    // 同优先级（不满足打断条件）入队
    const q1 = submitCue(
      state,
      cue({ cueId: "q-first", actionId: "wave", priority: 50, ttlMs: 10_000 }),
      ctx(),
      T0 + 10,
    );
    expect(q1).toEqual({ accepted: true, channel: "body", startImmediately: false });
    // 同优先级替换队首
    const q2 = submitCue(
      state,
      cue({ cueId: "q-second", actionId: "celebrate", priority: 50, ttlMs: 10_000 }),
      ctx(),
      T0 + 20,
    );
    expect(q2).toEqual({ accepted: true, channel: "body", startImmediately: false });
    // 低优先级挤不掉
    const lo = submitCue(
      state,
      cue({ cueId: "q-low", actionId: "nod", priority: 30 }),
      ctx(),
      T0 + 30,
    );
    expect(lo).toEqual({ accepted: false, reason: "queue_full" });
    // 当前动作结束后：队首 q-second 提升
    tickDirector(state, ctx(), T0 + 5000);
    expect(activeOn(state, "body")?.cue.cueId).toBe("q-second");
  });

  it("TTL：过期的排队动作出队时静默丢弃（不补演）", () => {
    const state = createDirectorState();
    submitCue(state, cue({ cueId: "running", durationMs: 5000 }), ctx(), T0);
    submitCue(state, cue({ cueId: "late", actionId: "wave", ttlMs: 1000 }), ctx(), T0 + 10);
    tickDirector(state, ctx(), T0 + 5000);
    expect(activeOn(state, "body")).toBeNull();
  });

  it("TTL：提交时已过期的 cue 直接拒绝", () => {
    const state = createDirectorState();
    const verdict = submitCue(state, cue({ createdAt: T0 - 3000, ttlMs: 2000 }), ctx(), T0);
    expect(verdict).toEqual({ accepted: false, reason: "expired" });
  });
});

describe("one-shot 结束与恢复", () => {
  it("到期自然结束（ended 上报），通道清空回 state loop", () => {
    const state = createDirectorState();
    submitCue(state, cue({ durationMs: 1000 }), ctx(), T0);
    let tick = tickDirector(state, ctx(), T0 + 999);
    expect(tick.ended).toHaveLength(0);
    tick = tickDirector(state, ctx(), T0 + 1000);
    expect(tick.ended).toHaveLength(1);
    expect(activeOn(state, "body")).toBeNull();
  });
});

describe("冷却", () => {
  it("冷却期内重复提交被拒；冷却过后放行", () => {
    const state = createDirectorState();
    submitCue(state, cue({ cooldownMs: 3000, durationMs: 500 }), ctx(), T0);
    const blocked = submitCue(
      state,
      cue({ cooldownMs: 3000, cueId: "c2", createdAt: T0 + 1000 }),
      ctx(),
      T0 + 1000,
    );
    expect(blocked).toEqual({ accepted: false, reason: "cooldown" });
    const allowed = submitCue(
      state,
      cue({ cooldownMs: 3000, cueId: "c3", createdAt: T0 + 3000 }),
      ctx(),
      T0 + 3000,
    );
    expect(allowed.accepted).toBe(true);
  });
});

describe("省电降档", () => {
  it("decorationsPaused：低优先级拒绝（power_save），系统级放行", () => {
    const state = createDirectorState();
    const paused = ctx({ decorationsPaused: true });
    expect(submitCue(state, cue(), paused, T0)).toEqual({
      accepted: false,
      reason: "power_save",
    });
    expect(
      submitCue(state, cue({ priority: BUSY_GUARD_PRIORITY, actionId: "surprised" }), paused, T0)
        .accepted,
    ).toBe(true);
  });
});

describe("非法输入", () => {
  it("未知通道 / 优先级越界 / 负时长 → invalid", () => {
    const state = createDirectorState();
    expect(submitCue(state, cue({ channel: "voice" as never }), ctx(), T0).accepted).toBe(false);
    expect(submitCue(state, cue({ priority: 120 }), ctx(), T0)).toEqual({
      accepted: false,
      reason: "invalid",
    });
    expect(submitCue(state, cue({ durationMs: -1 }), ctx(), T0)).toEqual({
      accepted: false,
      reason: "invalid",
    });
  });
});

describe("工作状态的工具反射不受守卫拦截（working 非守卫对象）", () => {
  it("working 状态下低优先级工具 cue 正常执行", () => {
    const state = createDirectorState();
    const context = ctx({ state: "working" as CharacterState });
    const verdict = submitCue(
      state,
      cue({ actionId: "celebrate", source: "tool", priority: 60 }),
      context,
      T0,
    );
    expect(verdict.accepted).toBe(true);
  });
});

describe("性能（M-B 验收：反射纯逻辑 <16ms/帧）", () => {
  it("1000 次提交+推进总耗时 <500ms，单次 <16ms", () => {
    const state = createDirectorState();
    const context = ctx();
    let now = T0;
    const start = performance.now();
    for (let i = 0; i < 1000; i++) {
      submitCue(
        state,
        cue({ cueId: `perf-${i}`, actionId: "nod", durationMs: 16, cooldownMs: 0 }),
        context,
        now,
      );
      tickDirector(state, context, now);
      now += 16;
    }
    const total = performance.now() - start;
    expect(total).toBeLessThan(500);
    // 单帧（提交+推进）远低于一帧预算
    expect(total / 1000).toBeLessThan(16);
  });
});
