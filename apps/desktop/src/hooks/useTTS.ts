/**
 * useTTS —— 语音播放编排（M1-S2，功能清单 5.1）。
 *
 * 文字流开始时选择展示时间轴，全文定型后尝试语音；无语音或准备过慢时，
 * 节拍随可见文字推进。取消／切换使声音、排队节拍与异步结果一起失效。
 * 静音只停止声音并切回文字展示，不取消回答本身的表演。
 */
import { useEffect } from "react";
import { create } from "zustand";
import { configApi } from "../api/configClient";
import { ttsApi } from "../api/ttsClient";
import { sanitizeSpeechText } from "../cue/speechText";
import { ttsPlayer } from "../character/ttsPlayer";
import { useConversation, type ConversationState } from "../store/conversation";
import { voiceEvents } from "../store/voiceEvents";

export interface ReplyPlayback {
  messageId: string;
  runId: string | null;
  mode: "waiting" | "text" | "audio";
  text: string;
  complete: boolean;
}

interface TTSState {
  playing: boolean;
  engine: string | null;
  /** 播报上下文（M-C）：cueScheduler 的句对齐基准；playing=false 时仍保留末次值 */
  speechText: string;
  speechStartedAt: number;
  speechDurationMs: number | null;
  /** 回复展示独立于声音；epoch 在取消／切换时使旧节拍与异步结果失效。 */
  reply: ReplyPlayback | null;
  replyEpoch: number;
}

const TTS_INITIAL = {
  playing: false,
  engine: null,
  speechText: "",
  speechStartedAt: 0,
  speechDurationMs: null,
  reply: null,
  replyEpoch: 0,
};

/** CharacterStage 据此把播报期角色态视为 talking（服务端 text.end 后即 idle）。 */
export const useTTSState = create<TTSState>(() => ({ ...TTS_INITIAL }));

/** 播放令牌：stop 后使在途合成失效，避免停播后被迟到音频复活。 */
let session = 0;

ttsPlayer.onEnded = () => useTTSState.setState({ playing: false, engine: null });

function stopAudio(): void {
  session += 1;
  ttsPlayer.stop();
  useTTSState.setState({ playing: false, engine: null });
}

export function stopSpeaking(): void {
  stopAudio();
  useTTSState.setState((s) => ({ reply: null, replyEpoch: s.replyEpoch + 1 }));
}

type SpeechOutcome = "played" | "unavailable" | "cancelled";
/** 合成并播报全文；设置面板试听按钮共用。失败一律静默降级。
 *  M-F：播报前净化文本——剥离全角舞台指示（（眨眨眼）等保留气泡展示、
 *  不进语音）+ markdown 格式符号（**加粗**不再被读成「星号星号」）。 */
export async function speakText(
  rawText: string,
  overrides: { voiceId?: string; rate?: number } = {},
  signal?: AbortSignal,
): Promise<SpeechOutcome> {
  const text = sanitizeSpeechText(rawText);
  if (!text.trim()) return "unavailable";
  if (signal?.aborted) return "cancelled";
  stopAudio();
  const token = session;
  const cancelled = () => token !== session || signal?.aborted;
  const abort = () => {
    if (token === session) stopAudio();
  };
  signal?.addEventListener("abort", abort, { once: true });
  try {
    const voice = await configApi.getVoice().catch(() => null);
    if (cancelled()) return "cancelled";
    if (!voice || !voice.ttsEnabled || voice.muted || !voice.connectionId) return "unavailable";

    const result = await ttsApi.stream(text, overrides, signal).catch(() => null);
    if (cancelled()) return "cancelled";
    if (!result?.audio) return "unavailable";

    let startedAt = Date.now();
    let durationMs: number | null = null;
    ttsPlayer.onStarted = (d) => {
      startedAt = Date.now();
      durationMs = d;
    };
    const started = await ttsPlayer.play(result.audio, voice.volume);
    if (cancelled()) return "cancelled";
    if (!started) return "unavailable";
    useTTSState.setState({
      playing: true,
      engine: result.engine,
      speechText: text,
      speechStartedAt: startedAt,
      speechDurationMs: durationMs,
    });
    return "played";
  } finally {
    signal?.removeEventListener("abort", abort);
  }
}

/** 语音准备的表演等待上限；不延长 cue TTL，也不截断仍在合成的有效音频。 */
export const SPEECH_PREPARE_TIMEOUT_MS = 4000;

/** 同步订阅事件归约，避免 React 批处理漏掉快速回合的开始／终态。 */
export function connectReplyPlayback(): () => void {
  let messageId: string | null = null;
  let preparing = false;
  let voiceExpected = true;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let controller: AbortController | null = null;

  const clearPreparation = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
    controller?.abort();
    controller = null;
    preparing = false;
  };
  const currentReply = (epoch: number) => {
    const s = useTTSState.getState();
    return s.replyEpoch === epoch ? s.reply : null;
  };
  const showText = (epoch: number) => {
    const reply = currentReply(epoch);
    if (reply) useTTSState.setState({ reply: { ...reply, mode: "text" } });
  };
  const fallbackToText = (epoch: number) => {
    const reply = currentReply(epoch);
    if (!reply) return;
    voiceExpected = false;
    clearPreparation();
    stopAudio();
    showText(epoch);
  };

  const startReply = (id: string) => {
    if (useTTSState.getState().reply) stopSpeaking();
    messageId = id;
    voiceExpected = true;
    const epoch = useTTSState.getState().replyEpoch;
    useTTSState.setState({
      reply: {
        messageId: id,
        runId: useConversation.getState().activeRunId,
        mode: "waiting",
        text: "",
        complete: false,
      },
    });
    timer = setTimeout(() => showText(epoch), SPEECH_PREPARE_TIMEOUT_MS);
    // 尽早判断无语音路径，让长回答中的节拍随文字流执行，而非等全文生成。
    void configApi
      .getVoice()
      .then((voice) => {
        if (currentReply(epoch)?.mode !== "waiting" || preparing) return;
        if (!voice.ttsEnabled || voice.muted || !voice.connectionId) fallbackToText(epoch);
      })
      .catch(() => {
        if (currentReply(epoch)?.mode === "waiting" && !preparing) fallbackToText(epoch);
      });
  };

  const prepareSpeech = (epoch: number) => {
    const reply = currentReply(epoch);
    if (!reply || !voiceExpected) return;
    clearPreparation();
    preparing = true;
    controller = new AbortController();
    // 软超时只释放动作：慢合成随后仍可播放，但不重建已推进的文字时间轴。
    timer = setTimeout(() => showText(epoch), SPEECH_PREPARE_TIMEOUT_MS);
    void speakText(reply.text, {}, controller.signal).then((outcome) => {
      const current = currentReply(epoch);
      if (!current) return;
      clearPreparation();
      if (outcome === "played" && current.mode === "waiting") {
        useTTSState.setState({ reply: { ...current, mode: "audio" } });
      } else if (outcome !== "played") {
        fallbackToText(epoch);
      }
    });
  };

  const sync = (state: ConversationState, previous: ConversationState) => {
    if (
      state.activeSessionId !== previous.activeSessionId ||
      (state.activeRunId !== null && state.activeRunId !== previous.activeRunId)
    ) {
      messageId = null;
      stopSpeaking();
    }
    if (
      state.lastFinishReason !== previous.lastFinishReason &&
      state.lastFinishReason !== null &&
      state.lastFinishReason !== "complete"
    ) {
      stopSpeaking();
      return;
    }
    const message = [...state.messages]
      .reverse()
      .find((m) => m.role === "assistant" && !m.fromHistory);
    if (!message) {
      if (messageId !== null) stopSpeaking();
      messageId = null;
      return;
    }
    if (message.id !== messageId) {
      if (!message.streaming && state.lastTextEndAt === previous.lastTextEndAt) return;
      startReply(message.id);
    }
    const { reply, replyEpoch } = useTTSState.getState();
    if (!reply) return; // 用户主动停止后，同一条消息的后续增量不能复活表演。
    const text = sanitizeSpeechText(message.text);
    const complete = !message.streaming;
    if (reply.text !== text || reply.complete !== complete) {
      useTTSState.setState({ reply: { ...reply, text, complete } });
    }
    if (complete && !reply.complete) prepareSpeech(replyEpoch);
  };

  const unsubscribePlayback = useTTSState.subscribe((state, previous) => {
    if (state.replyEpoch !== previous.replyEpoch) clearPreparation();
  });
  const unsubscribeConversation = useConversation.subscribe(sync);
  const initial = useConversation.getState();
  sync(initial, initial);

  let refresh = 0;
  const voiceChanged = () => {
    const request = ++refresh;
    const epoch = useTTSState.getState().replyEpoch;
    void configApi
      .getVoice()
      .then((voice) => {
        if (request === refresh && (!voice.ttsEnabled || voice.muted || !voice.connectionId))
          fallbackToText(epoch);
      })
      .catch(() => {
        if (request === refresh) fallbackToText(epoch);
      });
  };
  voiceEvents.addEventListener("voice-changed", voiceChanged);
  return () => {
    refresh += 1;
    unsubscribeConversation();
    unsubscribePlayback();
    voiceEvents.removeEventListener("voice-changed", voiceChanged);
    clearPreparation();
    stopSpeaking();
  };
}

export function useTTS(): void {
  useEffect(connectReplyPlayback, []);
}
