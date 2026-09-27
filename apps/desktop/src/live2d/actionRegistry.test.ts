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
  type Live2dActionPlan,
  type StaticActionPlan,
} from "./actionRegistry";
import type { ModelProfile } from "./stateMachine";

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
