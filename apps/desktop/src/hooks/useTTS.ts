/**
 * useTTS —— 语音播放编排（M1-S2，功能清单 5.1）。
 *
 * 触发：conversation store lastTextEndAt（回合全文定型）→ 合成播放；
 * 停播：新回合 TextStart（isSpeaking 真）、run 非 complete 终态（cancel/
 * interrupt/error）、静音/关闭翻转（voiceEvents）、新播放取代旧播放。
 * 引擎失败/204 → 静默回纯文本，永不阻塞对话（5.1 红线）。
 */
import { useEffect } from "react";
import { create } from "zustand";
import { configApi } from "../api/configClient";
import { ttsApi } from "../api/ttsClient";
import { sanitizeSpeechText } from "../cue/speechText";
import { ttsPlayer } from "../live2d/ttsPlayer";
import { useConversation } from "../store/conversation";
import { voiceEvents } from "../store/voiceEvents";

interface TTSState {
  playing: boolean;
  engine: string | null;
  /** 播报上下文（M-C）：cueScheduler 的句对齐基准；playing=false 时仍保留末次值 */
  speechText: string;
  speechStartedAt: number;
  speechDurationMs: number | null;
}

const TTS_INITIAL = {
  playing: false,
  engine: null,
  speechText: "",
  speechStartedAt: 0,
  speechDurationMs: null,
};

/** CharacterStage 据此把播报期角色态视为 talking（服务端 text.end 后即 idle）。 */
export const useTTSState = create<TTSState>(() => ({ ...TTS_INITIAL }));

/** 播放令牌：stop 后使在途合成失效，避免停播后被迟到音频复活。 */
let session = 0;

ttsPlayer.onEnded = () => useTTSState.setState({ playing: false, engine: null });

export function stopSpeaking(): void {
  session += 1;
  ttsPlayer.stop();
  useTTSState.setState({ playing: false, engine: null });
}
/** 合成并播报全文；设置面板试听按钮共用。失败一律静默降级。
 *  M-F：播报前净化文本——剥离全角舞台指示（（眨眨眼）等保留气泡展示、
 *  不进语音）+ markdown 格式符号（**加粗**不再被读成「星号星号」）。 */
export async function speakText(rawText: string): Promise<void> {
  const text = sanitizeSpeechText(rawText);
  if (!text.trim()) return;
  const token = ++session;
  ttsPlayer.stop();
  useTTSState.setState({ playing: false, engine: null });

  const voice = await configApi.getVoice().catch(() => null);
  if (!voice || !voice.ttsEnabled || voice.muted || token !== session) return;

  const result = await ttsApi.stream(text).catch(() => null);
  if (!result || token !== session) return;
  if (!result.audio) return; // 204：静音/纯文本降级 → 不出声、不报错

  // 播报上下文（M-C）：先记开始时刻与文本；真实时长由 onStarted（解码后）补——
  // 它在 play() 内部先于返回值触发，故用局部变量中转
  const startedAt = Date.now();
  let durationMs: number | null = null;
  ttsPlayer.onStarted = (d) => {
    durationMs = d;
  };
  const started = await ttsPlayer.play(result.audio);
  if (!started || token !== session) {
    if (token === session) stopSpeaking();
    return;
  }
  useTTSState.setState({
    playing: true,
    engine: result.engine,
    speechText: text,
    speechStartedAt: startedAt,
    speechDurationMs: durationMs,
  });
}

export function useTTS(): void {
  const lastTextEndAt = useConversation((s) => s.lastTextEndAt);
  const lastSpokenText = useConversation((s) => s.lastSpokenText);
  const isSpeaking = useConversation((s) => s.isSpeaking);
  const lastFinishReason = useConversation((s) => s.lastFinishReason);

  // 回合全文定型 → 播报
  useEffect(() => {
    if (lastTextEndAt > 0 && lastSpokenText) void speakText(lastSpokenText);
  }, [lastTextEndAt, lastSpokenText]);

  // 新回合开始（TextStart）→ 停旧播报
  useEffect(() => {
    if (isSpeaking) stopSpeaking();
  }, [isSpeaking]);

  // cancel/interrupt/error 终态 → 停播（complete 不停，刚起的播报要继续）
  useEffect(() => {
    if (lastFinishReason && lastFinishReason !== "complete") stopSpeaking();
  }, [lastFinishReason]);

  // 静音/关闭翻转 → 立即停播
  useEffect(() => {
    const refresh = () => {
      configApi
        .getVoice()
        .then((v) => {
          if (v.muted || !v.ttsEnabled) stopSpeaking();
        })
        .catch(() => {});
    };
    voiceEvents.addEventListener("voice-changed", refresh);
    return () => voiceEvents.removeEventListener("voice-changed", refresh);
  }, []);
}
