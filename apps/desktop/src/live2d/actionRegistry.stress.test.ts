import { describe, expect, it } from "vitest";
import { SEMANTIC_ACTIONS } from "@mochi/protocol";
import type { SkinAction, SkinSummary } from "../api/skinsClient";
import { resolveAction, TERMINAL_ACTION_ID, type Live2dActionPlan } from "./actionRegistry";
import type { ModelProfile } from "./stateMachine";

function live2dSkin(actions: SkinAction[]): Pick<SkinSummary, "resourceType" | "actions"> {
  return { resourceType: "live2d", actions };
}

describe("actionRegistry 严厉压力测试与矩阵测试", () => {
  it("超深层（100 层）降级链能正确解析到终点，且不爆栈", () => {
    const actions: SkinAction[] = [];
    for (let i = 0; i < 100; i += 1) {
      actions.push({
        id: `chain_${i}`,
        kind: "oneshot",
        priority: 50,
        channels: ["body"],
        live2d: { motionGroups: ["NonExistentGroup"] },
        fallback: i === 99 ? "idle_neutral" : `chain_${i + 1}`,
      });
    }
    const skin = live2dSkin(actions);
    const emptyProfile: ModelProfile = { motionGroups: [], expressions: [] };
    const plan = resolveAction("chain_0", skin, emptyProfile);
    expect(plan).toBeDefined();
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
    expect(plan.requestedId).toBe("chain_0");
  });

  it("复杂大环降级链（A->B->C->D->B）不会死循环，安全退出落内置兜底", () => {
    const actions: SkinAction[] = [
      {
        id: "loop_a",
        kind: "oneshot",
        priority: 50,
        channels: ["body"],
        live2d: { motionGroups: ["NoGroup"] },
        fallback: "loop_b",
      },
      {
        id: "loop_b",
        kind: "oneshot",
        priority: 50,
        channels: ["body"],
        live2d: { motionGroups: ["NoGroup"] },
        fallback: "loop_c",
      },
      {
        id: "loop_c",
        kind: "oneshot",
        priority: 50,
        channels: ["body"],
        live2d: { motionGroups: ["NoGroup"] },
        fallback: "loop_d",
      },
      {
        id: "loop_d",
        kind: "oneshot",
        priority: 50,
        channels: ["body"],
        live2d: { motionGroups: ["NoGroup"] },
        fallback: "loop_b", // 形成回环
      },
    ];
    const skin = live2dSkin(actions);
    const emptyProfile: ModelProfile = { motionGroups: [], expressions: [] };
    const plan = resolveAction("loop_a", skin, emptyProfile);
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
  });

  it("全零能力模型档案：全部 20 个语义动作均能平稳返回有效计划，零空指针", () => {
    const emptyProfile: ModelProfile = { motionGroups: [], expressions: [] };
    // 无清单动作（走默认映射）
    const skin = live2dSkin([]);

    for (const actionId of SEMANTIC_ACTIONS) {
      const plan = resolveAction(actionId, skin, emptyProfile);
      expect(plan).toBeDefined();
      expect(plan.requestedId).toBe(actionId);
      expect(plan.resourceType).toBe("live2d");
      // 无动作组时 motionGroup 必为 null
      expect(plan.motionGroup).toBeNull();
      expect(plan.expression).toBeNull();
    }
  });

  it("扩展包动作（MochiBow / MochiWave）命中后保留动作自定义参数属性", () => {
    const actions: SkinAction[] = [
      {
        id: "bow",
        kind: "oneshot",
        priority: 77,
        cooldownMs: 8888,
        interruptPolicy: "queue",
        channels: ["body"],
        live2d: { motionGroups: ["MochiBow"] },
      },
    ];
    const skin = live2dSkin(actions);
    const profile: ModelProfile = {
      motionGroups: ["Idle", "MochiBow"],
      expressions: [],
    };
    const plan = resolveAction("bow", skin, profile) as Live2dActionPlan;
    expect(plan.actionId).toBe("bow");
    expect(plan.motionGroup).toBe("MochiBow");
    expect(plan.priority).toBe(77);
    expect(plan.cooldownMs).toBe(8888);
    expect(plan.interruptPolicy).toBe("queue");
  });

  it("降级时保持最初 requestedId，便于调度层归因与冷却计算", () => {
    const actions: SkinAction[] = [
      {
        id: "custom_jump",
        kind: "oneshot",
        priority: 65,
        channels: ["body"],
        live2d: { motionGroups: ["MochiJump"] },
        fallback: "idle_neutral",
      },
    ];
    const skin = live2dSkin(actions);
    // 假设模型无 MochiJump
    const profile: ModelProfile = { motionGroups: ["Idle"], expressions: [] };
    const plan = resolveAction("custom_jump", skin, profile);
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
    expect(plan.requestedId).toBe("custom_jump");
  });
});
