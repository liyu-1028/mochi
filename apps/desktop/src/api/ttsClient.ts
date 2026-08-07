/**
 * ttsClient —— TTS 独立 HTTP 流通道封装（M1-S2，功能清单 5.1）。
 *
 * 音频不走 WS 协议（agent-events-v0.1 §10）；POST /tts/stream 返回
 * audio/mpeg|wav，``X-TTS-Engine`` 上报实际引擎（edge|local|text-fallback|muted）。
 * 204 = 无音频可播：调用方静默回纯文本，不阻塞对话（5.1 红线）。
 */
import { resolveHttpBaseUrl } from "./configClient";

export interface TtsVoiceOption {
  id: string;
  name: string;
  lang: string;
  gender: string;
}

export interface TtsSynthesisResult {
  /** null = 204（静音/降级/空文本），前端静默回纯文本 */
  audio: Blob | null;
  engine: string;
  mediaType: string | null;
}

export const ttsApi = {
  async stream(text: string): Promise<TtsSynthesisResult> {
    const resp = await fetch(`${resolveHttpBaseUrl()}/tts/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
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
};
