/**
 * actionRegistry 测试（M-A）：命中 / fallback 下探 / 语义词表收敛 / 链走死 / 循环防护。
 *
 * 验收（M-A）：resolveAction 全组合覆盖；旧皮肤（无 actions 字段）不崩溃且
 * 全部请求落到内置 idle_neutral 兜底（零回归前提）。
 */
import { describe, expect, it } from "vitest";
import type { SkinAction, SkinSummary } from "../api/skinsClient";
import {
  builtinFallbackPlan,
  resolveAction,
  TERMINAL_ACTION_ID,
  DEFAULT_LIVE2D_ACTIONS,
  type Live2dActionPlan,
  type StaticActionPlan,
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

function staticSkin(actions?: SkinAction[]): Pick<SkinSummary, "resourceType" | "actions"> {
  return { resourceType: "static", actions };
}

function live2dSkin(actions?: SkinAction[]): Pick<SkinSummary, "resourceType" | "actions"> {
  return { resourceType: "live2d", actions };
}

describe("静态皮肤路径", () => {
  it("命中：清单条目 + 包络注册 → static 计划（保留 priority/cooldown 声明）", () => {
    const skin = staticSkin([
      action("wave", { static: { animation: "wave" }, priority: 60, cooldownMs: 3000 }),
    ]);
    const plan = resolveAction("wave", skin, LIVE2D_PROFILE) as StaticActionPlan;
    expect(plan.resourceType).toBe("static");
    expect(plan.actionId).toBe("wave");
    expect(plan.requestedId).toBe("wave");
    expect(plan.envelope?.id).toBe("wave");
    expect(plan.priority).toBe(60);
    expect(plan.cooldownMs).toBe(3000);
  });

  it("fallback 一层：celebrate 声明 fallback=nod → 命中 nod 包络", () => {
    const skin = staticSkin([
      action("nod", { static: { animation: "nod" } }),
      action("celebrate", { static: { animation: "不存在的包络" }, fallback: "nod" }),
    ]);
    const plan = resolveAction("celebrate", skin, LIVE2D_PROFILE) as StaticActionPlan;
    expect(plan.actionId).toBe("nod");
    expect(plan.requestedId).toBe("celebrate");
    expect(plan.envelope?.id).toBe("nod");
  });

  it("词表收敛：请求未登记的语义动作（think）→ 落内置 idle_neutral 兜底", () => {
    const skin = staticSkin([action("wave", { static: { animation: "wave" } })]);
    const plan = resolveAction("think", skin, LIVE2D_PROFILE) as StaticActionPlan;
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
    expect(plan.envelope?.id).toBe(TERMINAL_ACTION_ID);
  });

  it("链走死：非语义词表 id 且无 fallback → 内置兜底，不抛异常", () => {
    const skin = staticSkin([action("custom_dance", { static: { animation: "无此包络" } })]);
    const plan = resolveAction("custom_dance", skin, LIVE2D_PROFILE) as StaticActionPlan;
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
  });

  it("循环防护：清单内互指 fallback → 落内置兜底，不挂死", () => {
    const skin = staticSkin([
      action("a", { static: { animation: "无此包络" }, fallback: "b" }),
      action("b", { static: { animation: "无此包络" }, fallback: "a" }),
    ]);
    const plan = resolveAction("a", skin, LIVE2D_PROFILE);
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
  });

  it("包络未注册但声明了 static 绑定 → 视为未命中继续降级", () => {
    const skin = staticSkin([
      action("dance", { static: { animation: "神秘舞步" }, fallback: "wave" }),
      action("wave", { static: { animation: "wave" } }),
    ]);
    const plan = resolveAction("dance", skin, LIVE2D_PROFILE) as StaticActionPlan;
    expect(plan.actionId).toBe("wave");
  });
});

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

  it("绑定与皮肤类型不符：live2d 皮肤上的 static-only 条目 → 降级", () => {
    const skin = live2dSkin([action("wave", { static: { animation: "wave" } })]);
    const plan = resolveAction("wave", skin, LIVE2D_PROFILE);
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
  });
});

describe("向后兼容（零回归前提）", () => {
  it("旧皮肤（无 actions 字段）：任何请求都安全落兜底", () => {
    const plan = resolveAction("wave", staticSkin(undefined), LIVE2D_PROFILE) as StaticActionPlan;
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
    expect(plan.envelope?.id).toBe(TERMINAL_ACTION_ID);
    expect(plan.priority).toBe(10);
  });

  it("皮肤未就绪（null）：安全落兜底", () => {
    const plan = resolveAction("wave", null, LIVE2D_PROFILE);
    expect(plan.actionId).toBe(TERMINAL_ACTION_ID);
  });

  it("内置兜底计划（live2d）：不切动作、不换表情", () => {
    const plan = builtinFallbackPlan("live2d", "celebrate") as Live2dActionPlan;
    expect(plan.motionGroup).toBeNull();
    expect(plan.expression).toBeNull();
    expect(plan.requestedId).toBe("celebrate");
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

describe("M-A/M-B 验收证据：12 动作全词表可解析", () => {
  const STATIC_BASELINE_IDS = [
    "idle_neutral",
    "look_around",
    "wave",
    "nod",
    "shake_head",
    "celebrate",
    "comfort",
    "surprised",
    "stretch",
    "doze",
  ];

  it("Hiyori 能力档案：12 个语义动作均有合法解析（含降级），播放组必为模型实际拥有", () => {
    for (const id of SEMANTIC_ACTIONS) {
      const plan = resolveAction(id, live2dSkin(undefined), HIYORI_PROFILE);
      expect(plan, id).toBeTruthy();
      if (plan.resourceType === "live2d") {
        expect(
          plan.motionGroup === null || HIYORI_PROFILE.motionGroups.includes(plan.motionGroup),
          `${id} motionGroup=${plan.motionGroup}`,
        ).toBe(true);
      }
    }
  });

  it("静态基线皮肤：12 个语义动作均有合法解析（think/listen 按设计降级）", () => {
    const staticBaseline = {
      resourceType: "static" as const,
      actions: STATIC_BASELINE_IDS.map((id) => ({
        id,
        static: { animation: id },
        fallback: id === "idle_neutral" ? undefined : "idle_neutral",
      })),
    };
    for (const id of SEMANTIC_ACTIONS) {
      const plan = resolveAction(id, staticBaseline, LIVE2D_PROFILE) as StaticActionPlan;
      expect(plan, id).toBeTruthy();
      if (["think", "listen"].includes(id)) {
        expect(plan.actionId, `${id} 应降级到兜底`).toBe(TERMINAL_ACTION_ID);
      } else {
        expect(plan.envelope, id).toBeTruthy();
      }
    }
  });

  it("Live2D 默认映射覆盖除 idle_neutral 外的全部词表（含两项降级设计）", () => {
    const ids = DEFAULT_LIVE2D_ACTIONS.map((a) => a.id);
    expect(ids.length).toBe(11);
    expect(ids).not.toContain("idle_neutral");
    expect(
      DEFAULT_LIVE2D_ACTIONS.filter((a) => a.fallback === "idle_neutral").map((a) => a.id),
    ).toEqual(["stretch", "doze"]);
  });
});
