/**
 * reflexRules —— 本地反射规则（M-B，纯函数）。
 *
 * 确定性事件（触摸/工具生命周期）不问 LLM，直接换算成 director cue
 * （调研报告 §3.3：目标 100ms 内给出身体/表情反馈）。
 *
 * 规则表（与 rollout plan B3 对齐）：
 * - 单击 tap → body `nod`（轻拍回应）；
 * - 连续轻戳（2s 内 ≥3 次）→ body `surprised`（连续戳 ≠ 轻拍）；
 * - 按住/拖起（pointerdown 500ms 未抬起）→ body `surprised`（被拿起，交互级优先级）；
 * - 拖拽释放（拖起后的 pointerup）→ body `idle_neutral`（recover，回状态 loop）；
 * - 工具执行中 → body `think`；
 * - 工具成功 → body `celebrate` + face `happy`；
 * - 工具失败 → face `worried`（担忧表情，非语义词表项，见 FACE_REFLEX_PRESETS）；
 * - 工具被拒 → body `shake_head`。
 *
 * 优先级/冷却默认值镜像 actionRegistry 的 DEFAULT_LIVE2D_ACTIONS 基线；
 * 皮肤声明优先。静态包络时长解析已随静态皮肤类型下线移除。
 */

import type { SkinAction } from "../api/skinsClient";
import type { CueSource, DirectorChannel, DirectorCue } from "./actionDirector";
import { DOZE_DURATION_MS, WINK_DURATION_MS } from "./stateMachine";

/** 连续轻戳判定窗口（ms） */
export const TAP_WINDOW_MS = 2000;
/** 窗口内达到此次数视为「连续戳」 */
export const TAP_REPEAT_COUNT = 3;
/** 按住判定：pointerdown 后未抬起达此时长 → 「被拿起」 */
export const HOLD_THRESHOLD_MS = 500;
/** Live2D one-shot 动作窗口（motion 实际时长未知，超时后由状态 loop 自然接管） */
export const LIVE2D_ACTION_MS = 2500;
/** face 通道表情覆盖时长（ms） */
export const FACE_OVERRIDE_MS = 2000;

/** 优先级/冷却/时长缺省（镜像 DEFAULT_LIVE2D_ACTIONS 基线；皮肤声明优先）。
 *  durationMs 缺省 = LIVE2D_ACTION_MS；参数包络类动作给实际包络时长（M-F） */
const DEFAULTS: Record<string, { priority: number; cooldownMs: number; durationMs?: number }> = {
  idle_neutral: { priority: 10, cooldownMs: 0 },
  look_around: { priority: 20, cooldownMs: 15_000 },
  wave: { priority: 50, cooldownMs: 3000 },
  nod: { priority: 50, cooldownMs: 3000 },
  shake_head: { priority: 50, cooldownMs: 3000 },
  celebrate: { priority: 60, cooldownMs: 10_000 },
  comfort: { priority: 60, cooldownMs: 10_000 },
  surprised: { priority: 70, cooldownMs: 8000 },
  stretch: { priority: 30, cooldownMs: 20_000 },
  doze: { priority: 20, cooldownMs: 30_000, durationMs: DOZE_DURATION_MS },
  think: { priority: 40, cooldownMs: 5000 },
  listen: { priority: 50, cooldownMs: 3000 },
  wink: { priority: 50, cooldownMs: 2500, durationMs: WINK_DURATION_MS },
  // G1（L1 包络扩容）：与 BODY_ACTION_ENVELOPES 时长对齐
  pout: { priority: 50, cooldownMs: 2500, durationMs: 900 },
  laugh: { priority: 60, cooldownMs: 4000, durationMs: 1200 },
  shy_shake: { priority: 50, cooldownMs: 4000, durationMs: 1100 },
  alert: { priority: 45, cooldownMs: 3000, durationMs: 800 },
  // face 通道表情 id 缺省：信息性覆盖，不抢系统级
  happy: { priority: 55, cooldownMs: 2000 },
  sad: { priority: 60, cooldownMs: 5000 },
  confused: { priority: 40, cooldownMs: 2000 },
  neutral: { priority: 10, cooldownMs: 0 },
  // worried 仅反射用（不在语义词表）：数值由 FACE_REFLEX_PRESETS 消费
  worried: { priority: 60, cooldownMs: 5000 },
};

export type ToolReflexStatus = "running" | "success" | "error" | "denied";

let cueSeq = 0;

/**
 * 构造 cue：one-shot 时长用固定窗口（motion 实际时长未知，超时后由状态
 * loop 自然接管）；优先级/冷却先查皮肤声明，缺省回落内置表。
 */
export function buildCue(
  actionId: string,
  opts: {
    channel: DirectorChannel;
    source: CueSource;
    now: number;
    actions?: readonly SkinAction[];
    ttlMs?: number;
    /** 覆盖优先级（如「被拿起」= 用户交互级，需过高优先级守卫） */
    priority?: number;
    /** 覆盖时长（如参数包络动作的实际包络时长，M-F） */
    durationMs?: number;
  },
): DirectorCue {
  const skinEntry = opts.actions?.find((a) => a.id === actionId);
  const fallback = DEFAULTS[actionId] ?? { priority: 50, cooldownMs: 0 };
  // v3（G3）：skin 条目 durationMs（包络/自定义动作的实际时长）> 内置兖底 > 通用窗口
  const durationMs =
    opts.durationMs ?? skinEntry?.durationMs ?? fallback.durationMs ?? LIVE2D_ACTION_MS;
  cueSeq += 1;
  return {
    cueId: `reflex-${opts.now}-${cueSeq}`,
    actionId,
    channel: opts.channel,
    priority: opts.priority ?? skinEntry?.priority ?? fallback.priority,
    interruptPolicy: skinEntry?.interruptPolicy ?? "replace",
    cooldownMs: skinEntry?.cooldownMs ?? fallback.cooldownMs,
    ttlMs: opts.ttlMs ?? 2000,
    durationMs,
    source: opts.source,
    createdAt: opts.now,
  };
}

/** 连续轻戳检测：2s 窗口内 ≥3 次 → true（调用方负责维护时间戳列表）。 */
export function isRepeatTap(tapTimes: readonly number[], now: number): boolean {
  const window = tapTimes.filter((t) => now - t <= TAP_WINDOW_MS);
  return window.length >= TAP_REPEAT_COUNT;
}

/** 工具生命周期 → cue 序列（0~2 个；body+face 可并行）。
 *  语义对齐 rollout plan B3：start=think、success=celebrate+happy、
 *  error=worried（担忧表情）、denied=shake_head。 */
export function toolReflexCues(
  status: ToolReflexStatus,
  opts: { now: number; actions?: readonly SkinAction[] },
): DirectorCue[] {
  const base = { now: opts.now, actions: opts.actions };
  switch (status) {
    case "running":
      return [buildCue("think", { ...base, channel: "body", source: "tool", ttlMs: 1000 })];
    case "success":
      return [
        buildCue("celebrate", { ...base, channel: "body", source: "tool" }),
        buildCue("happy", { ...base, channel: "face", source: "tool", ttlMs: 1000 }),
      ];
    case "error":
      return [buildCue("worried", { ...base, channel: "face", source: "tool", ttlMs: 1000 })];
    case "denied":
      return [buildCue("shake_head", { ...base, channel: "body", source: "tool" })];
  }
}
