/**
 * cueScheduler —— character.cue 节拍调度（M-C C3，纯逻辑）。
 *
 * 服务端发来的 reply cue 按 `sync` 与 TTS 播报对齐：
 * - immediate：立即到期；
 * - speech_start：播报开始（beginSpeech）时到期；
 * - sentence_boundary：第 sentenceIndex 句开始播报时到期（句起点按字符占比
 *   在音频时长上估算，见 sentences.ts；无音频时按时长估算）；
 * - speech_end：播报结束时到期。
 *
 * 丢弃规则（协议 §5.6，验收项）：
 * - 信封 ts + ttlMs 已过 → 到达即丢（expired）；
 * - run 结束后到达 → store 层丢弃（不在本模块）；
 * - 排队期间过期 → dueCues 巡检时丢弃，不补演。
 *
 * 确定性：无定时器，由渲染帧循环以 now 巡检 dueCues；全部时序由显式参数驱动，
 * vitest 可精确推演（乱序/迟到/超 TTL 用例）。
 */

import type { CharacterCueData } from "@mochi/protocol";
import type { DirectorCue } from "../live2d/actionDirector";
import { sentenceStartTimes } from "./sentences";

export type SubmitVerdict = "accepted" | "expired";

interface PendingCue {
  cue: CharacterCueData;
  /** 信封时间戳（ttl 基准） */
  envelopeTs: number;
  /** 到达时刻（本地时钟，过期巡检基准） */
  receivedAt: number;
}

export interface CueSchedulerState {
  pending: PendingCue[];
  /** 播报上下文；null = 未在播报 */
  speech: {
    text: string;
    /** 播报起点（本地时钟） */
    startedAt: number;
    /** 各句起点（相对播报起点的 ms 偏移，sentences.ts 估算） */
    starts: number[];
    /** 预计播报结束时刻（本地时钟） */
    endsAt: number;
  } | null;
  fired: Set<string>;
}

export function createCueScheduler(): CueSchedulerState {
  return { pending: [], speech: null, fired: new Set() };
}

/** 提交一条 cue：过期即丢；其余按 sync 排队等 dueCues 到期。 */
export function submitCue(
  state: CueSchedulerState,
  cue: CharacterCueData,
  envelopeTs: number,
  now: number,
): SubmitVerdict {
  if (envelopeTs + cue.ttlMs <= now) return "expired";
  state.pending.push({ cue, envelopeTs, receivedAt: now });
  return "accepted";
}

/** 播报开始：记录句起点（相对播报起点）与预计结束时刻。 */
export function beginSpeech(
  state: CueSchedulerState,
  fullText: string,
  durationMs: number | null,
  startedAt: number,
): void {
  state.speech = {
    text: fullText,
    startedAt,
    starts: sentenceStartTimes(fullText, durationMs),
    endsAt: startedAt + (durationMs ?? Math.max(1200, Math.round(fullText.length * 180))),
  };
}

/** 播报结束：终点提前到当前时刻（真实结束早于估算时，speech_end cue 提前到期）。 */
export function endSpeech(state: CueSchedulerState, now: number): void {
  if (state.speech) state.speech.endsAt = Math.min(state.speech.endsAt, now);
}

/** 新回合：清空排队、播报上下文与已发记录（旧回合节拍全部作废）。 */
export function resetCues(state: CueSchedulerState): void {
  state.pending = [];
  state.speech = null;
  state.fired.clear();
}

/** cue → DirectorCue 的换算闭包（组件层提供：需要皮肤解析时长/冷却）。 */
export type CueConverter = (
  cue: CharacterCueData,
  channel: "face" | "body",
  now: number,
) => DirectorCue | null;

function cueDueAt(state: CueSchedulerState, p: PendingCue): number | null {
  const cue = p.cue;
  if (cue.sync === "immediate") return p.receivedAt;
  if (!state.speech) return null; // speech_start/sentence/speech_end 都依赖播报上下文
  if (cue.sync === "speech_start") return state.speech.startedAt;
  if (cue.sync === "sentence_boundary") {
    const idx = Math.max(1, cue.sentenceIndex ?? 1);
    const starts = state.speech.starts;
    return state.speech.startedAt + starts[Math.min(idx, starts.length) - 1];
  }
  return state.speech.endsAt; // speech_end
}

/**
 * 巡检：返回本轮到期的 DirectorCue（已换算），并清理已发/过期项。
 * 未到期的继续排队；到 arrive 时播报上下文尚未建立的 sync 类 cue 继续等待，
 * 直到 ttl 耗尽被丢弃（不补演）。
 */
export function dueCues(
  state: CueSchedulerState,
  now: number,
  convert: CueConverter,
): DirectorCue[] {
  const due: DirectorCue[] = [];
  const keep: PendingCue[] = [];
  for (const p of state.pending) {
    // 过期巡检：到达后始终未等到对齐点 → 丢弃（不补演）
    if (p.envelopeTs + p.cue.ttlMs <= now) continue;
    const dueAt = cueDueAt(state, p);
    if (dueAt === null || dueAt > now) {
      keep.push(p);
      continue;
    }
    const channels: Array<"face" | "body"> = [];
    if (p.cue.channels.face) channels.push("face");
    if (p.cue.channels.body) channels.push("body");
    for (const channel of channels) {
      if (state.fired.has(`${p.cue.cueId}:${channel}`)) continue;
      state.fired.add(`${p.cue.cueId}:${channel}`);
      const converted = convert(p.cue, channel, now);
      if (converted) due.push(converted);
    }
  }
  state.pending = keep;
  return due;
}
