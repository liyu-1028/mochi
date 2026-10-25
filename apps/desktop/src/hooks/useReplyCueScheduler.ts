/** 回复展示时间轴 → 共享 cueScheduler；两种渲染路径使用同一生命周期。 */
import { useEffect, useRef, type RefObject } from "react";
import type { CharacterCueData } from "@mochi/protocol";
import { cancelReplyActions, type DirectorState } from "../character/actionDirector";
import {
  beginSpeech,
  createCueScheduler,
  endSpeech,
  resetCues,
  submitCue,
  updateTextProgress,
  type CueSchedulerState,
} from "../cue/cueScheduler";
import { useTTSState } from "./useTTS";

/** 舞台排水可能晚于回合切换；按关联 id 再校验，不能把旧队列装入新时间轴。 */
export function scheduleReplyCue(
  scheduler: CueSchedulerState,
  cue: CharacterCueData,
  ts: number,
  now: number,
): void {
  if (cue.source === "reply" || (cue.source === "proactive" && (cue.messageId || cue.runId))) {
    const reply = useTTSState.getState().reply;
    if (
      !reply ||
      (cue.messageId && cue.messageId !== reply.messageId) ||
      (cue.runId && cue.runId !== reply.runId)
    )
      return;
  }
  submitCue(scheduler, cue, ts, now);
}

export function connectReplyCueScheduler(
  scheduler: CueSchedulerState,
  director: DirectorState,
): () => void {
  let epoch = useTTSState.getState().replyEpoch;
  let audioStartedAt: number | null = null;
  const sync = () => {
    const state = useTTSState.getState();
    if (state.replyEpoch !== epoch) {
      resetCues(scheduler);
      cancelReplyActions(director);
      epoch = state.replyEpoch;
      audioStartedAt = null;
    }
    if (state.reply?.mode === "text") {
      updateTextProgress(scheduler, state.reply.text, state.reply.complete, Date.now());
      audioStartedAt = null;
    } else if (state.reply?.mode === "audio") {
      if (audioStartedAt !== state.speechStartedAt) {
        audioStartedAt = state.speechStartedAt;
        beginSpeech(scheduler, state.speechText, state.speechDurationMs, state.speechStartedAt);
      }
      if (!state.playing) endSpeech(scheduler, Date.now());
    }
  };
  sync();
  return useTTSState.subscribe(sync);
}

export function useReplyCueScheduler(director: RefObject<DirectorState>) {
  const scheduler = useRef(createCueScheduler());
  useEffect(() => connectReplyCueScheduler(scheduler.current, director.current), [director]);
  return scheduler;
}
