/**
 * useVoiceInput —— 按住说话（ADR-0007-R1）：MediaRecorder 采集 → 客户端
 * 定转 WAV → 服务端转写 → 文字回填。60s 上限自动停；cancel() 丢弃。
 */

import { useCallback, useRef, useState } from "react";
import { blobToWav } from "../audio/wav";
import { ttsApi } from "../api/ttsClient";
import { stopSpeaking } from "./useTTS";

export type VoiceInputState = "idle" | "recording" | "transcribing" | "error";

/** 录音自动停上限（paraformer 输入足够，16kHz mono PCM16 ≈ 1.9MB）。 */
export const MAX_RECORD_MS = 60_000;

const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"];

/** 采集失败 → 提示键：权限拒绝单独引导，其余归转写失败。 */
export function micErrorKey(err: unknown): string {
  return err instanceof DOMException && err.name === "NotAllowedError"
    ? "chat.micPermissionDenied"
    : "chat.asrFailed";
}

export function useVoiceInput(onErrorKey: (key: string) => void) {
  const [state, setState] = useState<VoiceInputState>("idle");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | null>(null);

  const cleanup = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    recorderRef.current?.stop();
    recorderRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    chunksRef.current = [];
  }, []);

  const finish = useCallback(
    async (discard: boolean) => {
      const recorder = recorderRef.current;
      if (!recorder) return "idle" as VoiceInputState;
      const chunks = chunksRef.current;
      const stopped = new Promise<Blob>((resolve) => {
        recorder.onstop = () => resolve(new Blob(chunks, { type: recorder.mimeType }));
        recorder.stop();
      });
      recorderRef.current = null;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      chunksRef.current = [];
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      if (discard) {
        setState("idle");
        return "idle" as VoiceInputState;
      }
      setState("transcribing");
      try {
        const blob = await stopped;
        const wav = await blobToWav(blob);
        const result = await ttsApi.asrTranscribe(wav);
        if (!result.text) {
          onErrorKey("chat.asrEmpty");
          setState("error");
        } else {
          setState("idle");
          return result.text;
        }
      } catch {
        onErrorKey("chat.asrFailed");
        setState("error");
      }
      return null;
    },
    [onErrorKey],
  );

  const start = useCallback(async (): Promise<boolean> => {
    if (state !== "idle") return false;
    if (!navigator.mediaDevices?.getUserMedia) {
      onErrorKey("chat.micUnsupported");
      setState("error");
      return false;
    }
    stopSpeaking(); // 防播报外放被麦克风收音
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MIME_CANDIDATES.find((t) => MediaRecorder.isTypeSupported(t));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.start(250);
      streamRef.current = stream;
      recorderRef.current = recorder;
      setState("recording");
      timerRef.current = window.setTimeout(() => void finish(false), MAX_RECORD_MS);
      return true;
    } catch (err) {
      onErrorKey(micErrorKey(err));
      setState("error");
      return false;
    }
  }, [state, finish, onErrorKey]);

  /** 返回转写文本（取消/失败返回 null）。 */
  const stop = useCallback(() => finish(false), [finish]);
  const cancel = useCallback(() => void finish(true), [finish]);

  return { state, start, stop, cancel, cleanup };
}
