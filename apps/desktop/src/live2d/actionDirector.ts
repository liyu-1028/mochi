/**
 * actionDirector —— 分通道动作调度核（M-B，纯逻辑，确定性无随机源）。
 *
 * 调研报告 §8.5 规则的落地：
 * - 通道：face / body / effect 各自独立调度（voice / locomotion 预留）；
 *   face 与 body 并行执行——body one-shot 永不清除表情（AIRI 教训）；
 * - 单槽队列：每通道最多保留 1 个待执行动作，新入队按优先级替换；
 * - TTL：过期 cue 不补演（提交时与出队时各判一次）；
 * - 冷却：按 actionId 计，冷却期内重复提交被 ignore；
 * - 打断守卫：说话（TTS）与拖拽期间，低于系统级（>=80）的 cue 直接拒绝，
 *   高优先级系统动作可打断 idle；
 * - 恢复：one-shot 到期自然结束，通道回到「当前 state 决定的 loop」
 *   （调用方持续应用 state 计划，director 只负责 one-shot 叠加窗口）。
 *
 * 全部决策确定性（无随机源），vitest 全表覆盖；随机性属上游选择策略（M-D）。
 */

import { ACTION_CHANNELS, type ActionChannel, type CharacterState } from "@mochi/protocol";
import type { InterruptPolicy } from "../api/skinsClient";

/** 本地可执行通道：从协议词表派生（剔除预留的 voice/locomotion），
 *  协议通道改名时此处编译期报错，不再硬编码漂移（验收工程问题 2） */
export type DirectorChannel = Extract<ActionChannel, "face" | "body" | "effect">;

export const DIRECTOR_CHANNELS: readonly DirectorChannel[] = ACTION_CHANNELS.filter(
  (c): c is DirectorChannel => c === "face" || c === "body" || c === "effect",
);

/** 系统级优先级线：>= 此值的 cue 可打断说话/拖拽（低优先级不得打扰用户交互） */
export const BUSY_GUARD_PRIORITY = 80;

export type CueSource = "reflex" | "tool" | "state" | "proactive" | "reply" | "system";

export interface DirectorCue {
  cueId: string;
  actionId: string;
  channel: DirectorChannel;
  /** 0~100，>=80 为系统级 */
  priority: number;
  interruptPolicy: InterruptPolicy;
  /** 提交时刻起的有效期；过期不补演 */
  ttlMs: number;
  /** 动作冷却（按 actionId 计） */
  cooldownMs: number;
  /** one-shot 预计时长（包络/动作时长由调用方从皮肤声明解析） */
  durationMs: number;
  source: CueSource;
  createdAt: number;
}

/** 提交时刻的运行上下文（组件层组装，纯值） */
export interface DirectorContext {
  /** 角色状态（有效态：ttsPlaying 时视为 talking） */
  state: CharacterState;
  /** TTS 播报中（= talking，打断守卫对象） */
  speaking: boolean;
  /** 窗口拖拽中（打断守卫对象） */
  dragging: boolean;
  /** 性能护栏降档暂停装饰动画（省电） */
  decorationsPaused: boolean;
}

export type RejectReason =
  "expired" | "cooldown" | "busy_guard" | "power_save" | "ignored" | "queue_full" | "invalid";

export type AcceptOrReject =
  | { accepted: true; channel: DirectorChannel; startImmediately: boolean }
  | { accepted: false; reason: RejectReason };

export interface ActiveAction {
  cue: DirectorCue;
  startedAt: number;
  endsAt: number;
}

export interface TickResult {
  started: ActiveAction[];
  /** 自然到期的 one-shot（通道回 state loop） */
  ended: ActiveAction[];
}

interface ChannelRuntime {
  active: ActiveAction | null;
  queued: DirectorCue | null;
}

export interface DirectorState {
  channels: Record<DirectorChannel, ChannelRuntime>;
  /** actionId → 冷却截止时刻（ms 纪元） */
  cooldownUntil: Record<string, number>;
}

export function createDirectorState(): DirectorState {
  return {
    channels: {
      face: { active: null, queued: null },
      body: { active: null, queued: null },
      effect: { active: null, queued: null },
    },
    cooldownUntil: {},
  };
}

function isBusy(ctx: DirectorContext): boolean {
  return ctx.speaking || ctx.state === "talking" || ctx.dragging;
}

/** 纯函数：单个 cue 提交决策（不落状态，落状态在 submitCue 中统一进行） */
function decide(
  state: DirectorState,
  cue: DirectorCue,
  ctx: DirectorContext,
  now: number,
): AcceptOrReject {
  if (!DIRECTOR_CHANNELS.includes(cue.channel)) return { accepted: false, reason: "invalid" };
  if (cue.priority < 0 || cue.priority > 100) return { accepted: false, reason: "invalid" };
  if (cue.durationMs < 0) return { accepted: false, reason: "invalid" };
  if (now - cue.createdAt > cue.ttlMs) return { accepted: false, reason: "expired" };
  if ((state.cooldownUntil[cue.actionId] ?? 0) > now) {
    return { accepted: false, reason: "cooldown" };
  }
  // 省电降档：仅系统级信息性 cue 放行（装饰性动作暂停）。
  // reply 节拍豁免：它是回答本身的表演（M-C），不是装饰，低帧率下仍应演出
  if (ctx.decorationsPaused && cue.priority < BUSY_GUARD_PRIORITY && cue.source !== "reply") {
    return { accepted: false, reason: "power_save" };
  }
  // 打断守卫：说话/拖拽期间，低优先级不得打扰（直接拒绝，不排队）。
  // reply 节拍豁免：它就发生在播报期内、由服务端按句对齐（M-C C3），
  // 是「说话时的表演」而非打断；proactive 同理豁免（M-D）：系统选定的
  // 主动表演（如长任务庆祝）常发生在回合尾段，属表演本体非打断；
  // 反射来源仍受守卫约束
  if (
    isBusy(ctx) &&
    cue.priority < BUSY_GUARD_PRIORITY &&
    cue.source !== "reply" &&
    cue.source !== "proactive"
  ) {
    return { accepted: false, reason: "busy_guard" };
  }
  return { accepted: true, channel: cue.channel, startImmediately: false };
}

/**
 * 提交一个 cue。返回决策结果；被接受时或立即开始（通道空闲），或入单槽队列。
 */
export function submitCue(
  state: DirectorState,
  cue: DirectorCue,
  ctx: DirectorContext,
  now: number,
): AcceptOrReject {
  const verdict = decide(state, cue, ctx, now);
  if (!verdict.accepted) return verdict;

  const channel = state.channels[verdict.channel];
  if (channel.active === null) {
    // 通道空闲：注意 active 可能刚在本帧 tick 中结束——startImmediately 表达此意
    channel.active = { cue, startedAt: now, endsAt: now + cue.durationMs };
    if (cue.cooldownMs > 0) state.cooldownUntil[cue.actionId] = now + cue.cooldownMs;
    return { ...verdict, startImmediately: true };
  }

  const activePriority = channel.active.cue.priority;
  if (cue.interruptPolicy === "ignore") {
    return { accepted: false, reason: "ignored" };
  }
  if (cue.interruptPolicy === "replace" && cue.priority > activePriority) {
    // 高优先级替换正在执行的 one-shot（被替换者不进队列、不补演）
    channel.active = { cue, startedAt: now, endsAt: now + cue.durationMs };
    if (cue.cooldownMs > 0) state.cooldownUntil[cue.actionId] = now + cue.cooldownMs;
    return { ...verdict, startImmediately: true };
  }
  // 单槽队列：同/高优先级替换队首，低优先级挤不掉
  if (channel.queued !== null && cue.priority < channel.queued.priority) {
    return { accepted: false, reason: "queue_full" };
  }
  channel.queued = cue;
  return { ...verdict, startImmediately: false };
}

/**
 * 每帧推进：结算到期 one-shot、从单槽队列提升下一个可执行动作。
 * 必须先于消费方读 channels 调用（同帧提交的 cue 在下一帧才开始播放）。
 * ctx 预留：未来按上下文过滤提升（如省电时跳过装饰性队列项）。
 */
export function tickDirector(state: DirectorState, _ctx: DirectorContext, now: number): TickResult {
  const result: TickResult = { started: [], ended: [] };
  for (const channel of DIRECTOR_CHANNELS) {
    const rt = state.channels[channel];
    if (rt.active !== null && now >= rt.active.endsAt) {
      result.ended.push(rt.active);
      rt.active = null;
    }
    if (rt.active === null && rt.queued !== null) {
      const queued = rt.queued;
      rt.queued = null;
      if (now - queued.createdAt <= queued.ttlMs) {
        rt.active = { cue: queued, startedAt: now, endsAt: now + queued.durationMs };
        if (queued.cooldownMs > 0) {
          state.cooldownUntil[queued.actionId] = now + queued.cooldownMs;
        }
        result.started.push(rt.active);
      }
      // TTL 过期的排队动作静默丢弃（不补演）
    }
  }
  return result;
}

/** 通道当前是否有活跃 one-shot（渲染层查询） */
export function activeOn(state: DirectorState, channel: DirectorChannel): ActiveAction | null {
  return state.channels[channel].active;
}
