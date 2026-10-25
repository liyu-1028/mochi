/**
 * useVoiceInput —— 按住说话（ADR-0007-R1）：MediaRecorder 采集 → 客户端
 * 定转 WAV → 服务端转写 → 文字回填。60s 上限自动停；cancel() 丢弃。
 */

import { useEffect, useRef, useState } from "react";
import { blobToWav } from "../audio/wav";
import { ttsApi } from "../api/ttsClient";
import { stopSpeaking } from "./useTTS";

export type VoiceInputState = "idle" | "starting" | "recording" | "transcribing";

/** 录音自动停上限（paraformer 输入足够，16kHz mono PCM16 ≈ 1.9MB）。 */
export const MAX_RECORD_MS = 60_000;

const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"];

/** 采集失败 → 提示键：权限拒绝单独引导，其余归转写失败。 */
export function micErrorKey(err: unknown): string {
  return err instanceof DOMException && err.name === "NotAllowedError"
    ? "chat.micPermissionDenied"
    : "chat.asrFailed";
}

interface VoiceInputCallbacks {
  onStateChange: (state: VoiceInputState) => void;
  onErrorKey: (key: string) => void;
  onTranscript: (text: string) => void;
}

/** 一次按住说话的资源所有者：权限、录音、转写共用代际与取消入口。 */
export function createVoiceInput(callbacks: VoiceInputCallbacks) {
  let state: VoiceInputState = "idle";
  let generation = 0;
  let recorder: MediaRecorder | null = null;
  let stream: MediaStream | null = null;
  let chunks: Blob[] = [];
  let timer: ReturnType<typeof setTimeout> | null = null;
  let request: AbortController | null = null;

  const setState = (next: VoiceInputState) => {
    state = next;
    callbacks.onStateChange(next);
  };
  const releaseCapture = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
    if (recorder) {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      recorder.onerror = null;
      if (recorder.state !== "inactive") recorder.stop();
    }
    recorder = null;
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    chunks = [];
  };
  const cancel = () => {
    generation += 1;
    request?.abort();
    request = null;
    releaseCapture();
    setState("idle");
  };
  const fail = (key: string) => {
    cancel();
    callbacks.onErrorKey(key);
  };

  const stop = async (): Promise<string | null> => {
    if (state === "starting") {
      cancel(); // 松手时尚未授权，稍后到达的麦克风流必须立即释放。
      return null;
    }
    if (state !== "recording" || !recorder) return null;
    const token = generation;
    const current = recorder;
    const captured = chunks;
    recorder = null;
    if (timer !== null) clearTimeout(timer);
    timer = null;
    const stopped = new Promise<Blob>((resolve, reject) => {
      current.onstop = () => resolve(new Blob(captured, { type: current.mimeType }));
      current.onerror = reject;
      current.stop();
    });
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    chunks = [];
    request = new AbortController();
    const signal = request.signal;
    setState("transcribing");
    try {
      const blob = await stopped;
      if (token !== generation) return null;
      const wav = await blobToWav(blob);
      if (token !== generation) return null;
      const result = await ttsApi.asrTranscribe(wav, signal);
      if (token !== generation) return null;
      if (!result.text.trim()) {
        fail("chat.asrEmpty");
        return null;
      }
      setState("idle");
      callbacks.onTranscript(result.text);
      return result.text;
    } catch {
      if (token === generation) fail("chat.asrFailed");
      return null;
    } finally {
      if (token === generation) request = null;
    }
  };

  const start = async (): Promise<boolean> => {
    if (state !== "idle") return false;
    const token = ++generation;
    setState("starting");
    if (!navigator.mediaDevices?.getUserMedia) {
      fail("chat.micUnsupported");
      return false;
    }
    stopSpeaking();
    try {
      const acquired = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (token !== generation) {
        acquired.getTracks().forEach((track) => track.stop());
        return false;
      }
      stream = acquired;
      const mimeType = MIME_CANDIDATES.find((t) => MediaRecorder.isTypeSupported(t));
      recorder = new MediaRecorder(acquired, mimeType ? { mimeType } : undefined);
      const captured: Blob[] = [];
      chunks = captured;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) captured.push(event.data);
      };
      recorder.onerror = () => {
        if (token === generation) fail("chat.asrFailed");
      };
      recorder.start(250);
      setState("recording");
      timer = setTimeout(() => void stop(), MAX_RECORD_MS);
      return true;
    } catch (error) {
      if (token === generation) fail(micErrorKey(error));
      return false;
    }
  };
  return {
    get state() {
      return state;
    },
    start,
    stop,
    cancel,
  };
}

export function useVoiceInput(
  onErrorKey: (key: string) => void,
  onTranscript: (text: string) => void,
) {
  const [state, setState] = useState<VoiceInputState>("idle");
  const callbacks = useRef({ onErrorKey, onTranscript });
  callbacks.current = { onErrorKey, onTranscript };
  const mounted = useRef(true);
  const inputRef = useRef<ReturnType<typeof createVoiceInput> | null>(null);
  if (inputRef.current === null) {
    inputRef.current = createVoiceInput({
      onStateChange: (next) => {
        if (mounted.current) setState(next);
      },
      onErrorKey: (key) => {
        if (mounted.current) callbacks.current.onErrorKey(key);
      },
      onTranscript: (text) => {
        if (mounted.current) callbacks.current.onTranscript(text);
      },
    });
  }
  const input = inputRef.current;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      input.cancel();
    };
  }, [input]);
  return { state, start: input.start, stop: input.stop, cancel: input.cancel };
}
