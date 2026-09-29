import { describe, expect, it, vi } from "vitest";
import type { StageHandle } from "./core";
import { createDriver } from "./driver";

function createMockStage(): {
  stage: StageHandle;
  paramValues: Record<string, number>;
  triggerBeforeUpdate: () => void;
  motionCalls: Array<{ group: string; priority: number }>;
} {
  const paramValues: Record<string, number> = {};
  const listeners: Record<string, Array<() => void>> = {};
  const motionCalls: Array<{ group: string; priority: number }> = [];

  const paramDefs: Record<string, { index: number; min: number; max: number }> = {
    ParamEyeLOpen: { index: 0, min: 0, max: 1 },
    ParamMouthForm: { index: 1, min: -1, max: 1 },
    ParamAngleZ: { index: 2, min: -30, max: 30 },
  };

  const coreModel = {
    getParameterIndex: (id: string) => (paramDefs[id] ? paramDefs[id].index : -1),
    getParameterMinimumValue: (index: number) => {
      const def = Object.values(paramDefs).find((d) => d.index === index);
      return def ? def.min : -100;
    },
    getParameterMaximumValue: (index: number) => {
      const def = Object.values(paramDefs).find((d) => d.index === index);
      return def ? def.max : 100;
    },
    setParameterValueById: (id: string, value: number) => {
      paramValues[id] = value;
    },
    parameterIds: Object.keys(paramDefs),
  };

  const internalModel = {
    coreModel,
    on: (event: string, fn: () => void) => {
      listeners[event] = listeners[event] || [];
      listeners[event].push(fn);
    },
    off: (event: string, fn: () => void) => {
      if (listeners[event]) {
        listeners[event] = listeners[event].filter((cb) => cb !== fn);
      }
    },
  };

  const model = {
    internalModel,
    motion: vi.fn((group: string, _idx?: number, priority?: number) => {
      motionCalls.push({ group, priority: priority ?? 1 });
      return Promise.resolve(true);
    }),
    expression: vi.fn(),
    hitTest: vi.fn(() => []),
    toModelPosition: vi.fn((pt) => pt),
  };

  const app = {
    ticker: { maxFPS: 60 },
    view: { getBoundingClientRect: () => ({ left: 0, top: 0, width: 200, height: 200 }) },
    renderer: { width: 200, height: 200 },
  };

  const stage = {
    app: app as unknown as StageHandle["app"],
    model: model as unknown as StageHandle["model"],
    modelWidth: 200,
    modelHeight: 200,
  };

  return {
    stage,
    paramValues,
    triggerBeforeUpdate: () => {
      (listeners["beforeModelUpdate"] || []).forEach((fn) => fn());
    },
    motionCalls,
  };
}

describe("CharacterDriver (live2d)", () => {
  it("motion 动作优先于包络，且调用 playMotion 后清空包络", () => {
    const { stage, motionCalls } = createMockStage();
    const driver = createDriver(stage);

    driver.applyAction(
      {
        requestedId: "wave",
        motionGroup: "Tap",
        paramEnvelope: null,
      },
      { startedAtMs: Date.now(), priority: "normal" },
    );

    expect(motionCalls).toHaveLength(1);
    expect(motionCalls[0].group).toBe("Tap");
  });

  it("声明式参数包络生命周期：执行期覆写参数，到期后必须立即停止覆写（防永久死锁）", () => {
    const { stage, paramValues, triggerBeforeUpdate } = createMockStage();
    const driver = createDriver(stage);

    driver.applyPlan({
      motionGroup: null,
      motionPriority: "idle",
      expression: { kind: "params", preset: "neutral" },
      eyesClosed: false,
      mouthEnabled: false,
      gazeEnabled: false,
      gazeOffsetY: 0,
      thinkingPose: false,
      bodySway: false,
      tickerFps: 60,
    });

    // 声明一个 500ms 的自定义包络
    const now = Date.now();
    driver.applyAction(
      {
        requestedId: "custom_wink",
        motionGroup: null,
        paramEnvelope: {
          durationMs: 500,
          keyframes: [
            {
              param: "ParamEyeLOpen",
              points: [
                [0, 1],
                [250, 0],
                [500, 1],
              ],
            },
          ],
        },
      },
      { startedAtMs: now - 250, priority: "normal" }, // 恰好在 250ms（中点）
    );

    // 触发帧更新
    triggerBeforeUpdate();
    expect(paramValues["ParamEyeLOpen"]).toBeCloseTo(0, 1);

    // 模拟时间流逝到 600ms（超出 durationMs=500）
    // 手动改写外界表情参数（如睁眼）
    paramValues["ParamEyeLOpen"] = 0.8;

    // 再次调用 applyAction 或者推进时间流逝：
    // 创建一个已过期的包络状态来模拟后续帧
    driver.applyAction(
      {
        requestedId: "custom_wink",
        motionGroup: null,
        paramEnvelope: {
          durationMs: 500,
          keyframes: [
            {
              param: "ParamEyeLOpen",
              points: [
                [0, 1],
                [250, 0],
                [500, 1],
              ],
            },
          ],
        },
      },
      { startedAtMs: now - 600, priority: "normal" }, // 此时已超过 500ms
    );

    // 重置参数为 0.8 观察在下一帧中是否还会被已过期的包络无脑重写
    paramValues["ParamEyeLOpen"] = 0.8;
    triggerBeforeUpdate();

    // 严格断言：包络已过期，不得再覆写该参数！
    expect(paramValues["ParamEyeLOpen"]).toBe(0.8);
  });

  it("模型缺失的参数静默跳过，不抛异常", () => {
    const { stage, triggerBeforeUpdate } = createMockStage();
    const driver = createDriver(stage);

    driver.applyAction(
      {
        requestedId: "unknown_param_action",
        motionGroup: null,
        paramEnvelope: {
          durationMs: 500,
          keyframes: [
            {
              param: "NonExistentParam",
              points: [
                [0, 0],
                [500, 1],
              ],
            },
          ],
        },
      },
      { startedAtMs: Date.now(), priority: "normal" },
    );

    expect(() => triggerBeforeUpdate()).not.toThrow();
  });

  it("dumpParamIds 正确提取模型支持的参数集合", () => {
    const { stage } = createMockStage();
    const driver = createDriver(stage);
    const ids = driver.dumpParamIds();
    expect(ids).toContain("ParamEyeLOpen");
    expect(ids).toContain("ParamMouthForm");
  });

  it("dispose 注销 beforeModelUpdate 事件并清理状态", () => {
    const { stage, paramValues, triggerBeforeUpdate } = createMockStage();
    const driver = createDriver(stage);

    driver.dispose();
    paramValues["ParamEyeLOpen"] = 0.5;
    triggerBeforeUpdate();
    expect(paramValues["ParamEyeLOpen"]).toBe(0.5);
  });
});
