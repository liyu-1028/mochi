/**
 * actionRegistry 测试（M-A）：命中 / fallback 下探 / 语义词表收敛 / 链走死 / 循环防护。
 *
 * 验收（M-A）：resolveAction 全组合覆盖；旧皮肤（无 actions 字段）不崩溃且
 * 全部请求落到内置 idle_neutral 兜底（零回归前提）。
 * 静态皮肤路径已随静态皮肤类型下线移除（2026-09-28），相关用例删除。
 */
import { describe, expect, it } from "vitest";
import type { SkinAction, SkinSummary } from "../api/skinsClient";
import {
  builtinFallbackPlan,
  resolveAction,
  TERMINAL_ACTION_ID,
  DEFAULT_LIVE2D_ACTIONS,
  type Live2dActionPlan,
} from "./actionRegistry";
import { HIYORI_PROFILE, type ModelProfile } from "./stateMachine";
import { SEMANTIC_ACTIONS } from "@mochi/protocol";

const LIVE2D_PROFILE: ModelProfile = {
  motionGroups: ["Idle", "Tap", "Flick"],
  expressions: ["happy", "sad"],
};

function action(id: string, extra: Partial<SkinAction> = {}): SkinAction {
  return { id, kind: "oneshot", priority: 50, ...extra };
}

function live2dSkin(actions?: SkinAction[]): Pick<SkinSummary, "resourceType" | "actions"> {
  return { resourceType: "live2d", actions };
}

describe("Live2D 路径", () => {
  it("命中：motionGroups 按偏好取首个模型实际拥有的组", () => {
    const skin = live2dSkin([
      action("wave", { live2d: { motionGroups: ["Tap", "Idle"], expression: "happy" } }),
    ]);
    const plan = resolveAction("wave", skin, LIVE2D_PROFILE) as Live2dActionPlan;
    expect(plan.resourceType).toBe("live2d");
    expect(plan.motionGroup).toBe("Tap");
    expect(plan.expression).toBe("happy");
  });

  it("降级：声明的 motionGroups 模型全缺 → 沿 fallback 链", () => {
    const skin = live2dSkin([
      action("celebrate", { live2d: { motionGroups: ["不存在组"] }, fallback: "wave" }),
      action("wave", { live2d: { motionGroups: ["Flick"] } }),
    ]);
    const plan = resolveAction("celebrate", skin, LIVE2D_PROFILE) as Live2dActionPlan;
    expect(plan.actionId).toBe("wave");
    expect(plan.motionGroup).toBe("Flick");
  });

  it("expression 未在模型档案中 → expression 置 null，motion 保留", () => {
    const skin = live2dSkin([
      action("wave", { live2d: { motionGroups: ["Tap"], expression: "angry" } }),
    ]);
    const plan = resolveAction("wave", skin, LIVE2D_PROFILE) as Live2dActionPlan;
    expect(plan.motionGroup).toBe("Tap");
    expect(plan.expression).toBeNull();
  });

  it("motionGroups 全缺且无 expression → 视为未命中落兜底", () => {
    const skin = live2dSkin([action("wave", { live2d: { motionGroups: ["神秘组"] } })]);
    const plan = resolveAction("wave", skin, LIVE2D_PROFILE);
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
  });

  it("词表收敛：请求未登记的语义动作（think）无清单声明 → 落内置兜底", () => {
    const skin = live2dSkin([action("wave", { live2d: { motionGroups: ["Tap"] } })]);
    const plan = resolveAction("think", skin, LIVE2D_PROFILE);
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
  });

  it("链走死：非语义词表 id 且无 fallback → 内置兜底，不抛异常", () => {
    const skin = live2dSkin([action("custom_dance", { live2d: { motionGroups: ["无此组"] } })]);
    const plan = resolveAction("custom_dance", skin, LIVE2D_PROFILE);
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
  });

  it("循环防护：清单内互指 fallback → 落内置兜底，不挂死", () => {
    const skin = live2dSkin([
      action("a", { live2d: { motionGroups: ["无此组"] }, fallback: "b" }),
      action("b", { live2d: { motionGroups: ["无此组"] }, fallback: "a" }),
    ]);
    const plan = resolveAction("a", skin, LIVE2D_PROFILE);
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
  });

  it("priority/cooldown 保留清单声明", () => {
    const skin = live2dSkin([
      action("wave", { live2d: { motionGroups: ["Tap"] }, priority: 60, cooldownMs: 3000 }),
    ]);
    const plan = resolveAction("wave", skin, LIVE2D_PROFILE);
    expect(plan.priority).toBe(60);
    expect(plan.cooldownMs).toBe(3000);
  });
});

describe("声明式参数包络（v3，G3）", () => {
  it("仅声明 paramEnvelope（无 motion/expression 命中）→ 视为可演，包络透传到计划", () => {
    const envelope = {
      durationMs: 700,
      keyframes: [
        {
          param: "ParamEyeLOpen",
          points: [
            [0, 1],
            [700, 1],
          ] as const,
        },
      ],
    };
    const skin = live2dSkin([
      action("wink", {
        live2d: { motionGroups: ["Wink"], paramEnvelope: envelope },
        agentSelectable: true,
      }),
    ]);
    const plan = resolveAction("wink", skin, LIVE2D_PROFILE) as Live2dActionPlan;
    expect(plan.motionGroup).toBeNull(); // 模型无 Wink 组
    expect(plan.paramEnvelope).toEqual(envelope);
  });

  it("motionGroups 命中优先：包络仍随计划透传，由播放端按 motion > 包络顺序消费", () => {
    const envelope = {
      durationMs: 500,
      keyframes: [
        {
          param: "P",
          points: [
            [0, 0],
            [500, 1],
          ] as const,
        },
      ],
    };
    const skin = live2dSkin([
      action("wave", { live2d: { motionGroups: ["Tap"], paramEnvelope: envelope } }),
    ]);
    const plan = resolveAction("wave", skin, LIVE2D_PROFILE) as Live2dActionPlan;
    expect(plan.motionGroup).toBe("Tap");
    expect(plan.paramEnvelope).toEqual(envelope);
  });

  it("包络时长进计划源（skin 条目 durationMs 供 buildCue 占位窗口，见 reflexRules 测试）", () => {
    const skin = live2dSkin([
      action("bounce", {
        live2d: {
          paramEnvelope: {
            durationMs: 900,
            keyframes: [
              {
                param: "P",
                points: [
                  [0, 0],
                  [900, 0],
                ] as const,
              },
            ],
          },
        },
        durationMs: 900,
        agentSelectable: true,
      }),
    ]);
    const plan = resolveAction("bounce", skin, LIVE2D_PROFILE);
    expect(plan.actionId).toBe("bounce");
  });

  it("无任何 live2d 实现（绑定空）→ 未命中落兖底（原行为不变）", () => {
    const skin = live2dSkin([action("ghost", { live2d: { motionGroups: [] } })]);
    const plan = resolveAction("ghost", skin, LIVE2D_PROFILE);
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
  });
});

describe("向后兼容（零回归前提）", () => {
  it("皮肤未就绪（null）：安全落兜底", () => {
    const plan = resolveAction("wave", null, LIVE2D_PROFILE);
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
    expect(plan.motionGroup).toBeNull();
  });

  it("内置兜底计划：不切动作、不换表情", () => {
    const plan = builtinFallbackPlan("celebrate");
    expect(plan.motionGroup).toBeNull();
    expect(plan.expression).toBeNull();
    expect(plan.requestedId).toBe("celebrate");
    expect(plan.priority).toBe(10);
  });
});

describe("Live2D 默认映射（旧版导入皮肤无 actions 字段，M-B 验收补）", () => {
  const bareLive2d = live2dSkin(undefined);

  it("无 actions 的 live2d 皮肤：语义词表动作可解析到通用动作组", () => {
    const plan = resolveAction("wave", bareLive2d, HIYORI_PROFILE) as Live2dActionPlan;
    expect(plan.resourceType).toBe("live2d");
    expect(plan.motionGroup).toBe("Tap"); // Hiyori 拥有 Tap 组
  });

  it("模型缺组时沿 fallback 降级，不硬猜资源", () => {
    const plan = resolveAction("doze", bareLive2d, HIYORI_PROFILE) as Live2dActionPlan;
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
    expect(plan.motionGroup).toBeNull();
  });

  it("清单有 actions 时不套默认映射（皮肤声明优先）", () => {
    const skin = live2dSkin([action("wave", { live2d: { motionGroups: ["自定义组"] } })]);
    const plan = resolveAction("wave", skin, HIYORI_PROFILE);
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID); // 自定义组不存在，无默认救场
  });

  it("终点动作约束：idle_neutral 的 fallback 被忽略（前端兜底）", () => {
    const skin = live2dSkin([
      action("idle_neutral", { live2d: { motionGroups: ["无此组"] }, fallback: "nod" }),
      action("nod", { live2d: { motionGroups: ["Tap"] } }),
    ]);
    const plan = resolveAction("idle_neutral", skin, HIYORI_PROFILE);
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
  });
});

describe("M-A/M-B 验收证据：全词表可解析", () => {
  it("Hiyori 能力档案：全部语义动作均有合法解析（含降级），播放组必为模型实际拥有", () => {
    for (const id of SEMANTIC_ACTIONS) {
      const plan = resolveAction(id, live2dSkin(undefined), HIYORI_PROFILE);
      expect(plan, id).toBeTruthy();
      expect(
        plan.motionGroup === null || HIYORI_PROFILE.motionGroups.includes(plan.motionGroup),
        `${id} motionGroup=${plan.motionGroup}`,
      ).toBe(true);
    }
  });

  it("Live2D 默认映射覆盖除 idle_neutral 外的全部词表（stretch 降级，其余包络兑底）", () => {
    const ids = DEFAULT_LIVE2D_ACTIONS.map((a) => a.id);
    // 词表 17 项 - idle_neutral = 16；全部有默认映射（G1 后 doze 也可演）
    expect(ids.length).toBe(SEMANTIC_ACTIONS.length - 1);
    expect(ids).not.toContain("idle_neutral");
    expect(new Set(ids).size).toBe(ids.length); // 无重复
    // stretch 仍是唯一无诚实实现的降级设计；其余 fallback 到 idle_neutral
    // 的动作 = 包络兑底类（wink + G1 四项 + doze）
    expect(
      DEFAULT_LIVE2D_ACTIONS.filter((a) => a.fallback === "idle_neutral").map((a) => a.id),
    ).toEqual(["wink", "pout", "laugh", "shy_shake", "alert", "stretch", "doze"]);
  });

  it("G1 包络兑底：Hiyori 无专用组 → pout/laugh/shy_shake/alert 走内置包络计划", () => {
    for (const id of ["pout", "laugh", "shy_shake", "alert", "doze"] as const) {
      const plan = resolveAction(id, live2dSkin(undefined), HIYORI_PROFILE);
      expect(plan.motionGroup, id).toBeNull();
      expect(plan.requestedId, id).toBe(id); // driver 按 requestedId 查 BODY_ACTION_ENVELOPES
      expect(plan.actionId, id).toBe(TERMINAL_ACTION_ID); // 计划层面降级到兑底占位
    }
  });

  it("wink（M-F）：Hiyori 无 Wink 组 → 内置兑底计划（帧循环用参数包络演出）", () => {
    const plan = resolveAction("wink", live2dSkin(undefined), HIYORI_PROFILE);
    expect(plan.motionGroup).toBeNull(); // 无 motion 实现 → 兑底占位
    expect(plan.requestedId).toBe("wink"); // 包络表按 requestedId 查找

    // 皮肤声明了真实 Wink 组 → 播真 motion（包络不叠加）
    const skin = live2dSkin([action("wink", { live2d: { motionGroups: ["Wink", "Tap"] } })]);
    const declared = resolveAction("wink", skin, {
      motionGroups: ["Idle", "Wink"],
      expressions: [],
    });
    expect(declared.motionGroup).toBe("Wink");
  });
});
