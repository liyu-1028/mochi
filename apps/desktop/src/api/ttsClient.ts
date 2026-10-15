/**
 * ttsClient —— TTS 独立 HTTP 流通道封装（M1-S2，功能清单 5.1）。
 *
 * 音频不走 WS 协议（agent-events-v0.1 §10）；POST /tts/stream 返回
 * audio/mpeg，``X-TTS-Engine`` 上报实际引擎（cosyvoice|text-fallback|cloud-unconfigured|muted）。
 * 204 = 无音频可播：调用方静默回纯文本，不阻塞对话（5.1 红线）。
 */
import { resolveHttpBaseUrl } from "./configClient";

export interface TtsVoiceOption {
  id: string;
  name: string;
  lang: string;
  gender: string;
  /** 品类分组键（companion/assistant/support/dialect/child），用于 optgroup */
  category?: string;
}

export interface TtsSynthesisResult {
  /** null = 204（静音/降级/空文本），前端静默回纯文本 */
  audio: Blob | null;
  engine: string;
  mediaType: string | null;
}

export const ttsApi = {
  /** 试听可传 voiceId/rate 覆盖 [voice] 配置（选中即试当前音色）。 */
  async stream(
    text: string,
    overrides: { voiceId?: string; rate?: number } = {},
  ): Promise<TtsSynthesisResult> {
    const resp = await fetch(`${resolveHttpBaseUrl()}/tts/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, ...overrides }),
    });
    const engine = resp.headers.get("X-TTS-Engine") ?? "text-fallback";
    if (resp.status === 204) return { audio: null, engine, mediaType: null };
    if (!resp.ok) throw new Error(`TTS 合成失败（${resp.status}）`);
    return {
      audio: await resp.blob(),
      engine,
      mediaType: resp.headers.get("Content-Type"),
    };
  },

  async voices(): Promise<{ voices: TtsVoiceOption[]; default: string }> {
    const resp = await fetch(`${resolveHttpBaseUrl()}/tts/voices`);
    if (!resp.ok) throw new Error(`音色目录拉取失败（${resp.status}）`);
    return resp.json();
  },

  /** ASR 转写：恒传 audio/wav（16kHz mono PCM16，见 audio/wav.ts）。 */
  async asrTranscribe(blob: Blob): Promise<{ text: string }> {
    const form = new FormData();
    form.append("file", blob, "speech.wav");
    const resp = await fetch(`${resolveHttpBaseUrl()}/asr/transcribe`, {
      method: "POST",
      body: form,
    });
    if (!resp.ok) {
      const detail = await resp.json().catch(() => null);
      throw new Error(detail?.detail ?? `语音识别失败（${resp.status}）`);
    }
    return resp.json();
  },
};
