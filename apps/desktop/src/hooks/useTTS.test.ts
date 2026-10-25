/** 真实事件归约 → 回复展示 → 调度器／director；仅替代云请求与音频设备。 */
import type { CharacterCueData, ServerEvent } from "@mochi/protocol";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { configApi, type VoiceSettings } from "../api/configClient";
import { ttsApi } from "../api/ttsClient";
import { createDirectorState, submitCue as submitAction } from "../character/actionDirector";
import { ttsPlayer } from "../character/ttsPlayer";
import { createCueScheduler, dueCues, type CueConverter } from "../cue/cueScheduler";
import { useConversation } from "../store/conversation";
import { notifyVoiceChanged } from "../store/voiceEvents";
import { connectReplyCueScheduler, scheduleReplyCue } from "./useReplyCueScheduler";
import {
  connectReplyPlayback,
  SPEECH_PREPARE_TIMEOUT_MS,
  stopSpeaking,
  useTTSState,
} from "./useTTS";

vi.mock("../api/configClient", () => ({ configApi: { getVoice: vi.fn() } }));
vi.mock("../api/ttsClient", () => ({ ttsApi: { stream: vi.fn() } }));
vi.mock("../character/ttsPlayer", () => ({
  ttsPlayer: { play: vi.fn(), stop: vi.fn(), onStarted: null, onEnded: null },
}));

const voice: VoiceSettings = {
  ttsEnabled: true,
  connectionId: "bailian",
  voiceId: "longxing_v3",
  volume: 1,
  rate: 1,
  muted: false,
};
const ctx = { state: "idle", speaking: false, dragging: false, decorationsPaused: false } as const;
const convert: CueConverter = (cue, channel, now) => ({
  cueId: `${cue.cueId}:${channel}`,
  actionId: channel === "face" ? cue.channels.face!.emotion : cue.channels.body!.actionId,
  channel,
  priority: cue.priority,
  interruptPolicy: cue.interruptPolicy,
  ttlMs: cue.ttlMs,
  cooldownMs: 0,
  durationMs: 1000,
  source: "reply",
  createdAt: now,
});

let scheduler = createCueScheduler();
let director = createDirectorState();
let disconnectPlayback: () => void;
let disconnectScheduler: () => void;
let runId: string;
let messageId: string;

function event(type: string, data: Record<string, unknown>) {
  useConversation.getState().applyEvent({
    v: "0.1",
    type,
    id: crypto.randomUUID(),
    ts: Date.now(),
    data: { runId, messageId, ...data },
  } as ServerEvent);
}

function start(id = "1") {
  runId = `r-${id}`;
  messageId = `m-${id}`;
  event("run.started", { sessionId: "default" });
  event("text.start", { role: "assistant" });
}

function cue(overrides: Partial<CharacterCueData> = {}) {
  const data: CharacterCueData = {
    cueId: crypto.randomUUID(),
    runId,
    messageId,
    source: "reply",
    channels: { face: { emotion: "happy", intensity: 0.75 }, body: { actionId: "wave" } },
    sync: "speech_start",
    priority: 45,
    interruptPolicy: "replace",
    ttlMs: 15_000,
    ...overrides,
  };
  event("character.cue", { ...data });
  // 与舞台相同：先排水，再由帧循环取出到期动作。
  const state = useConversation.getState();
  for (const pending of state.pendingCues)
    scheduleReplyCue(scheduler, pending.cue, pending.ts, Date.now());
  state.consumePendingCues(state.pendingCues.length);
}

function frame() {
  const cues = dueCues(scheduler, Date.now(), convert);
  for (const cue of cues) submitAction(director, cue, ctx, Date.now());
  return cues.map((c) => `${c.channel}:${c.actionId}`);
}

function finish(text = "你好。世界！") {
  event("text.end", { fullText: text });
  event("run.finished", { reason: "complete" });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(100_000);
  vi.clearAllMocks();
  vi.mocked(configApi.getVoice).mockResolvedValue({ ...voice });
  vi.mocked(ttsApi.stream).mockResolvedValue({
    audio: new Blob(["audio"]),
    engine: "cosyvoice",
    mediaType: "audio/mpeg",
  });
  vi.mocked(ttsPlayer.play).mockImplementation(async () => {
    ttsPlayer.onStarted?.(2000);
    return true;
  });
  stopSpeaking();
  useConversation.setState({
    activeSessionId: "default",
    activeRunId: null,
    messages: [],
    pendingCues: [],
    cueRunIds: [],
    lastTextEndAt: 0,
    lastSpokenText: null,
    lastFinishReason: null,
    isSpeaking: false,
  });
  scheduler = createCueScheduler();
  director = createDirectorState();
  disconnectScheduler = connectReplyCueScheduler(scheduler, director);
  disconnectPlayback = connectReplyPlayback();
});

afterEach(() => {
  disconnectPlayback();
  disconnectScheduler();
  vi.useRealTimers();
});

describe("无语音的默认体验", () => {
  it.each([
    ["关闭语音", { ttsEnabled: false }],
    ["静音", { muted: true }],
    ["没有云语音连接", { connectionId: null }],
  ])("%s：文字生成中就播放双通道节拍，长回答不等全文完成", async (_label, patch) => {
    vi.mocked(configApi.getVoice).mockResolvedValue({ ...voice, ...patch });
    start();
    await vi.advanceTimersByTimeAsync(0);
    cue();
    event("text.delta", { delta: "（挥手）你好！" });
    expect(frame()).toEqual(["face:happy", "body:wave"]);
    await vi.advanceTimersByTimeAsync(20_000);
    event("text.delta", { delta: "我还在继续回答。" });
    expect(frame()).toEqual([]);
    finish();
    await vi.advanceTimersByTimeAsync(0);
    expect(ttsApi.stream).not.toHaveBeenCalled();
    expect(ttsPlayer.play).not.toHaveBeenCalled();
  });

  it("读取语音配置失败仍随文字演出", async () => {
    vi.mocked(configApi.getVoice).mockRejectedValue(new Error("offline"));
    start();
    cue();
    event("text.delta", { delta: "你好。" });
    await vi.advanceTimersByTimeAsync(0);
    expect(frame()).toEqual(["face:happy", "body:wave"]);
  });

  it("仅含动作描写的回答也能收口；不会重播历史消息", async () => {
    useConversation
      .getState()
      .hydrateHistory([
        { id: "h", role: "assistant", text: "旧回答", streaming: false, fromHistory: true },
      ]);
    expect(useTTSState.getState().reply).toBeNull();
    start();
    cue();
    finish("（挥手）");
    await vi.advanceTimersByTimeAsync(0);
    expect(frame()).toEqual(["face:happy", "body:wave"]);
    expect(ttsPlayer.play).not.toHaveBeenCalled();
  });
});

describe("音频对齐与回退", () => {
  it("已开启语音的长生成也先释放文字节拍，后续合成失败不丢掉句首动作", async () => {
    vi.mocked(ttsApi.stream).mockRejectedValue(new Error("offline"));
    start();
    await vi.advanceTimersByTimeAsync(0);
    cue();
    event("text.delta", { delta: "你好。" });
    await vi.advanceTimersByTimeAsync(SPEECH_PREPARE_TIMEOUT_MS);
    expect(frame()).toEqual(["face:happy", "body:wave"]);
    await vi.advanceTimersByTimeAsync(20_000);
    finish();
    await vi.advanceTimersByTimeAsync(0);
    expect(ttsApi.stream).toHaveBeenCalledTimes(1);
    expect(frame()).toEqual([]);
    expect(useTTSState.getState().reply?.mode).toBe("text");
  });

  it("正常语音按真实音频句起点与结束播放，run.finished 不清除节拍", async () => {
    start();
    await vi.advanceTimersByTimeAsync(0);
    event("text.delta", { delta: "你好。世界！" });
    cue({ channels: { body: { actionId: "wave" } } });
    cue({
      sync: "sentence_boundary",
      sentenceIndex: 2,
      channels: { face: { emotion: "sad", intensity: 1 } },
    });
    cue({ sync: "speech_end", channels: { face: { emotion: "neutral", intensity: 0 } } });
    expect(frame()).toEqual([]);
    finish();
    await vi.advanceTimersByTimeAsync(0);
    expect(useTTSState.getState().reply?.mode).toBe("audio");
    expect(frame()).toEqual(["body:wave"]);
    await vi.advanceTimersByTimeAsync(999);
    expect(frame()).toEqual([]);
    await vi.advanceTimersByTimeAsync(1);
    expect(frame()).toEqual(["face:sad"]);
    ttsPlayer.onEnded?.();
    expect(frame()).toEqual(["face:neutral"]);
  });

  it.each(["204", "request", "decode"])("%s 失败后回到文字节拍", async (failure) => {
    if (failure === "204")
      vi.mocked(ttsApi.stream).mockResolvedValue({
        audio: null,
        engine: "text-fallback",
        mediaType: null,
      });
    if (failure === "request") vi.mocked(ttsApi.stream).mockRejectedValue(new Error("503"));
    if (failure === "decode") vi.mocked(ttsPlayer.play).mockResolvedValue(false);
    start();
    cue();
    finish();
    await vi.advanceTimersByTimeAsync(0);
    expect(useTTSState.getState().reply?.mode).toBe("text");
    expect(frame()).toEqual(["face:happy", "body:wave"]);
  });

  it("合成过慢先用文字节拍；同回合迟到音频仍可播放但不重复动作", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof ttsApi.stream>>) => void;
    vi.mocked(ttsApi.stream).mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    start();
    cue();
    finish();
    await vi.advanceTimersByTimeAsync(SPEECH_PREPARE_TIMEOUT_MS);
    expect(frame()).toEqual(["face:happy", "body:wave"]);
    resolve({ audio: new Blob(["late"]), engine: "cosyvoice", mediaType: "audio/mpeg" });
    await vi.advanceTimersByTimeAsync(0);
    expect(ttsPlayer.play).toHaveBeenCalledTimes(1);
    expect(frame()).toEqual([]);
    expect(useTTSState.getState().reply?.mode).toBe("text");
    expect(useTTSState.getState().playing).toBe(true);
  });

  it("语音配置请求挂起也有文字回退上限", async () => {
    vi.mocked(configApi.getVoice).mockReturnValue(new Promise(() => {}));
    start();
    cue();
    event("text.delta", { delta: "你好" });
    await vi.advanceTimersByTimeAsync(SPEECH_PREPARE_TIMEOUT_MS);
    expect(frame()).toEqual(["face:happy", "body:wave"]);
  });

  it("播报中静音：保留去重记录，未播放的后句转为文字节拍", async () => {
    start();
    cue({ channels: { body: { actionId: "wave" } } });
    cue({
      sync: "sentence_boundary",
      sentenceIndex: 2,
      channels: { face: { emotion: "sad", intensity: 1 } },
    });
    finish();
    await vi.advanceTimersByTimeAsync(0);
    expect(frame()).toEqual(["body:wave"]);
    vi.mocked(configApi.getVoice).mockResolvedValue({ ...voice, muted: true });
    notifyVoiceChanged();
    await vi.advanceTimersByTimeAsync(0);
    expect(frame()).toEqual(["face:sad"]);
    expect(frame()).toEqual([]);
    expect(useTTSState.getState().playing).toBe(false);
  });
});

describe("回合与会话清理", () => {
  it("上一回合取消的原因不影响下一回合的文字表演", async () => {
    vi.mocked(configApi.getVoice).mockResolvedValue({ ...voice, ttsEnabled: false });
    start();
    event("run.finished", { reason: "cancelled" });
    start("2");
    cue();
    event("text.delta", { delta: "新的回复" });
    await vi.advanceTimersByTimeAsync(0);
    expect(frame()).toEqual(["face:happy", "body:wave"]);
    expect(useConversation.getState().lastFinishReason).toBeNull();
  });

  it.each(["cancelled", "interrupted", "error", "session", "new-run", "stop"])(
    "%s 清除排队和执行中的回复，迟到请求无效",
    async (reason) => {
      vi.mocked(configApi.getVoice).mockResolvedValue({ ...voice, ttsEnabled: false });
      start();
      await vi.advanceTimersByTimeAsync(0);
      cue();
      event("text.delta", { delta: "你好。" });
      frame();
      cue({ sync: "speech_end" });
      expect(director.channels.body.active).not.toBeNull();
      expect(scheduler.pending).toHaveLength(1);
      if (reason === "session") useConversation.getState().activateSession("new-session");
      else if (reason === "new-run") start("2");
      else if (reason === "stop") stopSpeaking();
      else if (reason === "error") event("run.error", { error: { message: "failed" } });
      else event("run.finished", { reason });
      expect(scheduler.pending).toEqual([]);
      expect(director.channels.body.active).toBeNull();
      expect(director.channels.face.active).toBeNull();
      await vi.advanceTimersByTimeAsync(20_000);
      expect(frame()).toEqual([]);
    },
  );

  it("准备语音时切换会话，旧合成完成不能复活声音或表演", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof ttsApi.stream>>) => void;
    vi.mocked(ttsApi.stream).mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    start();
    cue();
    finish();
    await vi.advanceTimersByTimeAsync(0);
    useConversation.getState().activateSession("new-session");
    resolve({ audio: new Blob(["late"]), engine: "cosyvoice", mediaType: "audio/mpeg" });
    await vi.advanceTimersByTimeAsync(0);
    expect(ttsPlayer.play).not.toHaveBeenCalled();
    expect(frame()).toEqual([]);
    expect(useTTSState.getState().reply).toBeNull();
  });

  it("旧 React 排水闭包不能把旧回合节拍装入新回合", async () => {
    vi.mocked(configApi.getVoice).mockResolvedValue({ ...voice, ttsEnabled: false });
    start();
    event("character.cue", {
      cueId: "old",
      source: "reply",
      channels: { body: { actionId: "wave" } },
      sync: "immediate",
      priority: 45,
      interruptPolicy: "replace",
      ttlMs: 15_000,
    });
    const old = useConversation.getState().pendingCues[0];
    start("2");
    await vi.advanceTimersByTimeAsync(0);
    scheduleReplyCue(scheduler, old.cue, old.ts, Date.now());
    expect(frame()).toEqual([]);
  });
});
