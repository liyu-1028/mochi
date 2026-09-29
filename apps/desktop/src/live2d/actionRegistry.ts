/**
 * actionRegistry —— 语义动作解析（M-A，纯函数）。
 *
 * (语义动作 id, 皮肤清单, 模型能力档案) → 动作计划：
 * - 命中清单条目 → 取 live2d 实现绑定（motion/expression）；
 * - 绑定不可用（motionGroups 全缺 / expression 不存在）→ 沿 fallback 链下探；
 * - 语义词表内动作天然向 idle_neutral 收敛；链走死 / 循环 → 内置 idle_neutral 计划。
 *
 * 静态皮肤包络路径已随静态皮肤类型下线移除（2026-09-28）。
 * 本模块只做解析不播放；调度（优先级/打断/队列/TTL）属 M-B Action Director。
 * 循环防护独立于服务端校验存在——前端永不因清单数据挂死。
 */

import { SEMANTIC_ACTIONS } from "@mochi/protocol";
import type {
  ActionKind,
  InterruptPolicy,
  ParamEnvelopeBinding,
  SkinAction,
  SkinSummary,
} from "../api/skinsClient";
import type { ModelProfile } from "./stateMachine";
import { DOZE_DURATION_MS } from "./stateMachine";

/** 内置兜底动作：全链路降级终点（协议规范 §11）。 */
export const TERMINAL_ACTION_ID = "idle_neutral";

/**
 * Live2D 默认动作映射（M-B 验收补）：用户导入的 Live2D 皮肤清单无 `actions`
 * 字段时（旧版导入），按模型通用动作组（Tap/Flick 系列）给全词表可解析的映射。
 * wink/pout/laugh/shy_shake/alert/doze 优先真实动作组，无则参数包络兑底
 * （BODY_ACTION_ENVELOPES，G1）；stretch 无通用诚实实现 → fallback 到
 * idle_neutral；模型实际不存在的组按未命中继续降级，绝不硬猜文件名。
 */
export const DEFAULT_LIVE2D_ACTIONS: readonly SkinAction[] = [
  {
    id: "wave",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["Tap", "Flick"] },
    priority: 50,
    cooldownMs: 3000,
    agentSelectable: true,
  },
  {
    id: "nod",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["Tap@Body", "Tap", "FlickDown"] },
    priority: 50,
    cooldownMs: 3000,
    agentSelectable: true,
  },
  {
    id: "shake_head",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["Flick@Body", "Flick"] },
    priority: 50,
    cooldownMs: 3000,
    agentSelectable: true,
  },
  {
    id: "celebrate",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["FlickUp", "Flick", "Tap"] },
    priority: 60,
    cooldownMs: 10_000,
    agentSelectable: true,
  },
  {
    id: "comfort",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["FlickDown", "Tap"] },
    priority: 60,
    cooldownMs: 10_000,
    agentSelectable: true,
  },
  {
    id: "surprised",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["FlickUp", "FlickDown", "Tap"] },
    priority: 70,
    cooldownMs: 8000,
    agentSelectable: true,
  },
  {
    id: "look_around",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["FlickUp", "Flick"] },
    priority: 20,
    cooldownMs: 15_000,
    agentSelectable: true,
  },
  {
    id: "think",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["Think", "Idle"] },
    priority: 40,
    cooldownMs: 5000,
    agentSelectable: true,
  },
  {
    id: "listen",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["FlickUp", "Idle"] },
    priority: 50,
    cooldownMs: 3000,
    agentSelectable: true,
  },
  {
    // wink（M-F）：优先用模型真实动作组（若皮肤声明）；Hiyori 等无专用组
    // 的模型走 fallback → idle_neutral 计划，帧循环用参数包络兑底
    id: "wink",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["Wink"] },
    fallback: "idle_neutral",
    priority: 50,
    cooldownMs: 2500,
    agentSelectable: true,
  },
  // ---- G1（L1 包络扩容）：同 wink 模式——有真实组优先，无则包络兑底 ----
  {
    id: "pout",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["Pout"] },
    fallback: "idle_neutral",
    priority: 50,
    cooldownMs: 2500,
    agentSelectable: true,
  },
  {
    id: "laugh",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["Laugh"] },
    fallback: "idle_neutral",
    priority: 60,
    cooldownMs: 4000,
    agentSelectable: true,
  },
  {
    id: "shy_shake",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["ShyShake"] },
    fallback: "idle_neutral",
    priority: 50,
    cooldownMs: 4000,
    agentSelectable: true,
  },
  {
    id: "alert",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["Alert"] },
    fallback: "idle_neutral",
    priority: 45,
    cooldownMs: 3000,
    agentSelectable: true,
  },
  {
    id: "stretch",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["Flick@Body"] },
    priority: 30,
    cooldownMs: 20_000,
    agentSelectable: true,
    fallback: "idle_neutral",
  },
  {
    // doze（G1 升级）：优先真实 Doze 组；无则参数包络兑底（打哈欠/犯困点头）
    id: "doze",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["Doze"] },
    durationMs: DOZE_DURATION_MS,
    priority: 20,
    cooldownMs: 30_000,
    agentSelectable: true,
    fallback: "idle_neutral",
  },
  // ---- G5（2b 资产解锁）：无内置兑底——仅当皮肤扩展包（G4）提供对应
  // motion3.json 才可演；组未命中 → fallback idle_neutral，与设计一致 ----
  {
    id: "jump",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["MochiJump"] },
    fallback: "idle_neutral",
    priority: 55,
    cooldownMs: 6000,
    agentSelectable: true,
  },
  {
    id: "spin",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["MochiSpin"] },
    fallback: "idle_neutral",
    priority: 55,
    cooldownMs: 8000,
    agentSelectable: true,
  },
  {
    id: "bow",
    kind: "oneshot",
    channels: ["body"],
    live2d: { motionGroups: ["MochiBow"] },
    fallback: "idle_neutral",
    priority: 45,
    cooldownMs: 5000,
    agentSelectable: true,
  },
];

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
  /** 命中的 motion group；null = 不切换动作（如纯表情/包络动作） */
  motionGroup: string | null;
  /** 命中的 expression 名；仅当模型档案实际拥有时非 null */
  expression: string | null;
  /**
   * 声明式参数包络（skin.json v3，G3）：清单原样透传，播放端按
   * motionGroup > paramEnvelope > 内置兖底顺序消费。不依赖模型档案
   * （缺参数运行时静默跳过），因此不参与「命中判定」。
   */
  paramEnvelope: ParamEnvelopeBinding | null;
}

export type ResolvedAction = Live2dActionPlan;

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
export function builtinFallbackPlan(requestedId: string): ResolvedAction {
  return {
    requestedId,
    actionId: TERMINAL_ACTION_ID,
    kind: "oneshot",
    priority: 10,
    interruptPolicy: "replace",
    cooldownMs: 0,
    resourceType: "live2d",
    motionGroup: null,
    expression: null,
    paramEnvelope: null,
  };
}

/** live2d 绑定 → 计划；motionGroups 全缺或 expression 不存在则返回 null（视为未命中）。 */
function resolveLive2d(
  requestedId: string,
  entry: SkinAction,
  profile: ModelProfile,
): Live2dActionPlan | null {
  const binding = entry.live2d;
  if (!binding) return null;
  const group = (binding.motionGroups ?? []).find((g) => profile.motionGroups.includes(g));
  const expression =
    binding.expression !== undefined && profile.expressions.includes(binding.expression)
      ? binding.expression
      : null;
  const paramEnvelope = binding.paramEnvelope ?? null;
  // 命中判定不包含 paramEnvelope：包络不依赖模型能力（缺参数运行时跳过），
  // 仅声明了包络（无 motion/expression 命中）也视为可演
  if (group === undefined && expression === null && paramEnvelope === null) return null;
  return {
    ...baseOf(requestedId, entry, entry.id),
    resourceType: "live2d",
    motionGroup: group ?? null,
    expression,
    paramEnvelope,
  };
}

/**
 * 语义动作解析主入口。skin 为 null（未就绪）时直接返回内置兜底。
 * 任何皮肤都保证返回非 null——调用方无需再判空。
 */
export function resolveAction(
  requestedId: string,
  skin: Pick<SkinSummary, "actions"> | null,
  profile: ModelProfile,
): ResolvedAction {
  if (!skin) return builtinFallbackPlan(requestedId);

  // 皮肤清单无动作时（旧版导入），回退内置 Live2D 默认映射
  const declared = (skin.actions?.length ?? 0) > 0 ? skin.actions : DEFAULT_LIVE2D_ACTIONS;
  const byId = new Map((declared ?? []).map((a) => [a.id, a]));
  const visited = new Set<string>();
  let current: string | undefined = requestedId;

  while (current !== undefined && !visited.has(current)) {
    visited.add(current);
    const entry = byId.get(current);

    if (entry) {
      const plan = resolveLive2d(requestedId, entry, profile);
      if (plan) return plan;
    }

    // 降级：清单声明的 fallback；语义词表内动作缺省向 idle_neutral 收敛；
    // 终点动作（idle_neutral）自身的 fallback 永远忽略（全链路兑底约束）
    const next: string | null | undefined =
      current === TERMINAL_ACTION_ID ? undefined : entry?.fallback;
    if (next !== undefined && next !== null) {
      current = next;
    } else if (entry === undefined && SEMANTIC_ACTIONS.includes(current as never)) {
      current = TERMINAL_ACTION_ID;
    } else {
      current = undefined; // 链走死
    }
  }

  return builtinFallbackPlan(requestedId);
}
