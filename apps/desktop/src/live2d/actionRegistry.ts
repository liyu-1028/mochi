/**
 * actionRegistry —— 语义动作解析（M-A，纯函数）。
 *
 * (语义动作 id, 皮肤清单, 模型能力档案) → 动作计划：
 * - 命中清单条目 → 按皮肤类型取实现绑定（live2d motion/expression 或 static 包络）；
 * - 绑定不可用（类型不符 / motionGroups 全缺 / 包络未注册）→ 沿 fallback 链下探；
 * - 语义词表内动作天然向 idle_neutral 收敛；链走死 / 循环 → 内置 idle_neutral 计划。
 *
 * 本模块只做解析不播放；调度（优先级/打断/队列/TTL）属 M-B Action Director。
 * 循环防护独立于服务端校验存在——前端永不因清单数据挂死。
 */

import { SEMANTIC_ACTIONS } from "@mochi/protocol";
import type { ActionKind, InterruptPolicy, SkinAction, SkinSummary } from "../api/skinsClient";
import { ACTION_ENVELOPES, type ActionEnvelope } from "./actionEnvelopes";
import type { ModelProfile } from "./stateMachine";

/** 内置兜底动作：全链路降级终点（协议规范 §11）。 */
export const TERMINAL_ACTION_ID = "idle_neutral";

interface ResolvedActionBase {
  /** 最初请求的动作 id（供调度层做冷却与日志归因） */
  requestedId: string;
  /** 实际命中的动作 id（经降级后可能 ≠ requestedId） */
  actionId: string;
  kind: ActionKind;
  priority: number;
  interruptPolicy: InterruptPolicy;
  cooldownMs: number;
}

export interface Live2dActionPlan extends ResolvedActionBase {
  resourceType: "live2d";
  /** 命中的 motion group；null = 不切换动作（如纯表情动作） */
  motionGroup: string | null;
  /** 命中的 expression 名；仅当模型档案实际拥有时非 null */
  expression: string | null;
}

export interface StaticActionPlan extends ResolvedActionBase {
  resourceType: "static";
  /** 静态包络；idle_neutral 兜底为 null 变换（保持当前 loop 原样） */
  envelope: ActionEnvelope | null;
}

export type ResolvedAction = Live2dActionPlan | StaticActionPlan;

function baseOf(
  requestedId: string,
  entry: SkinAction | undefined,
  actionId: string,
): ResolvedActionBase {
  return {
    requestedId,
    actionId,
    kind: entry?.kind ?? "oneshot",
    priority: entry?.priority ?? 50,
    interruptPolicy: entry?.interruptPolicy ?? "replace",
    cooldownMs: entry?.cooldownMs ?? 0,
  };
}

/** 内置 idle_neutral 兜底计划：不切动作、不换表情，仅作为调度层的合法占位。 */
export function builtinFallbackPlan(
  resourceType: "live2d" | "static",
  requestedId: string,
): ResolvedAction {
  const base: ResolvedActionBase = {
    requestedId,
    actionId: TERMINAL_ACTION_ID,
    kind: "oneshot",
    priority: 10,
    interruptPolicy: "replace",
    cooldownMs: 0,
  };
  if (resourceType === "live2d") {
    return { ...base, resourceType, motionGroup: null, expression: null };
  }
  return { ...base, resourceType, envelope: ACTION_ENVELOPES[TERMINAL_ACTION_ID] ?? null };
}

/** live2d 绑定 → 计划；motionGroups 全缺或 expression 不存在则返回 null（视为未命中）。 */
function resolveLive2d(
  requestedId: string,
  entry: SkinAction,
  profile: ModelProfile,
): Live2dActionPlan | null {
  const binding = entry.live2d;
  if (!binding) return null;
  const group = binding.motionGroups.find((g) => profile.motionGroups.includes(g));
  const expression =
    binding.expression !== undefined && profile.expressions.includes(binding.expression)
      ? binding.expression
      : null;
  if (group === undefined && expression === null) return null;
  return {
    ...baseOf(requestedId, entry, entry.id),
    resourceType: "live2d",
    motionGroup: group ?? null,
    expression,
  };
}

/** static 绑定 → 计划；包络未注册返回 null（声明诚实但前端无实现，走降级）。 */
function resolveStatic(requestedId: string, entry: SkinAction): StaticActionPlan | null {
  const binding = entry.static;
  if (!binding) return null;
  const envelope = ACTION_ENVELOPES[binding.animation];
  if (!envelope) return null;
  return {
    ...baseOf(requestedId, entry, entry.id),
    resourceType: "static",
    envelope,
  };
}

/**
 * 语义动作解析主入口。skin 为 null（未就绪）时直接返回内置兜底。
 * 任何皮肤都保证返回非 null——调用方无需再判空。
 */
export function resolveAction(
  requestedId: string,
  skin: Pick<SkinSummary, "resourceType" | "actions"> | null,
  profile: ModelProfile,
): ResolvedAction {
  if (!skin) return builtinFallbackPlan("static", requestedId);

  const byId = new Map((skin.actions ?? []).map((a) => [a.id, a]));
  const visited = new Set<string>();
  let current: string | undefined = requestedId;

  while (current !== undefined && !visited.has(current)) {
    visited.add(current);
    const entry = byId.get(current);

    if (entry) {
      const plan =
        skin.resourceType === "live2d"
          ? resolveLive2d(requestedId, entry, profile)
          : resolveStatic(requestedId, entry);
      if (plan) return plan;
    }

    // 降级：清单声明的 fallback；语义词表内动作缺省向 idle_neutral 收敛
    const next = entry?.fallback;
    if (next !== undefined && next !== null) {
      current = next;
    } else if (entry === undefined && SEMANTIC_ACTIONS.includes(current as never)) {
      current = TERMINAL_ACTION_ID;
    } else {
      current = undefined; // 链走死
    }
  }

  return builtinFallbackPlan(skin.resourceType, requestedId);
}
