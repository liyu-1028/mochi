/** 语音输入纯函数与常量测试（node 环境直测，仓库惯例）。 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ttsApi } from "../api/ttsClient";
import { blobToWav } from "../audio/wav";
import { createVoiceInput, MAX_RECORD_MS, micErrorKey } from "./useVoiceInput";

vi.mock("../api/ttsClient", () => ({ ttsApi: { asrTranscribe: vi.fn() } }));
vi.mock("../audio/wav", () => ({ blobToWav: vi.fn() }));
vi.mock("./useTTS", () => ({ stopSpeaking: vi.fn() }));

describe("micErrorKey", () => {
  it("权限拒绝 → 引导系统设置", () => {
    const denied = new DOMException("denied", "NotAllowedError");
    expect(micErrorKey(denied)).toBe("chat.micPermissionDenied");
  });
  it("其他失败（含非 DOM 异常）→ 转写失败", () => {
    expect(micErrorKey(new DOMException("abort", "AbortError"))).toBe("chat.asrFailed");
    expect(micErrorKey(new Error("network"))).toBe("chat.asrFailed");
  });
});

describe("MAX_RECORD_MS", () => {
  it("60s 上限（16kHz mono PCM16 ≈ 1.9MB，远低于服务端 20MB）", () => {
    expect(MAX_RECORD_MS).toBe(60_000);
  });
});

function makeStream() {
  const track = { stop: vi.fn() };
  return { getTracks: () => [track] };
}

let recorders: FakeRecorder[];
class FakeRecorder {
  static isTypeSupported = () => true;
  static failStart = false;
  state = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: ((error: Error) => void) | null = null;
  constructor() {
    recorders.push(this);
  }
  start() {
    if (FakeRecorder.failStart) throw new Error("device failure");
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    queueMicrotask(() => {
      this.ondataavailable?.({ data: new Blob(["recorded"]) });
      this.onstop?.();
    });
  }
}

describe("录音生命周期与文字回填", () => {
  let input: ReturnType<typeof createVoiceInput>;
  let callbacks: {
    onStateChange: ReturnType<typeof vi.fn>;
    onErrorKey: ReturnType<typeof vi.fn>;
    onTranscript: ReturnType<typeof vi.fn>;
  };
  let getUserMedia: ReturnType<typeof vi.fn>;
  let stream: ReturnType<typeof makeStream>;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    recorders = [];
    FakeRecorder.failStart = false;
    stream = makeStream();
    getUserMedia = vi.fn().mockResolvedValue(stream);
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
    vi.stubGlobal("MediaRecorder", FakeRecorder);
    vi.mocked(blobToWav).mockResolvedValue(new Blob(["wav"]));
    vi.mocked(ttsApi.asrTranscribe).mockResolvedValue({ text: "识别文字" });
    callbacks = { onStateChange: vi.fn(), onErrorKey: vi.fn(), onTranscript: vi.fn() };
    input = createVoiceInput(callbacks);
  });
  afterEach(() => {
    input.cancel();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("手动松开回填一次并释放麦克风", async () => {
    expect(await input.start()).toBe(true);
    expect(await input.stop()).toBe("识别文字");
    expect(callbacks.onTranscript.mock.calls).toEqual([["识别文字"]]);
    expect(stream.getTracks()[0].stop).toHaveBeenCalled();
    expect(input.state).toBe("idle");
  });

  it("60 秒自动停止与手动停止使用同一个回填入口", async () => {
    await input.start();
    await vi.advanceTimersByTimeAsync(MAX_RECORD_MS - 1);
    expect(input.state).toBe("recording");
    await vi.advanceTimersByTimeAsync(1);
    expect(callbacks.onTranscript.mock.calls).toEqual([["识别文字"]]);
    expect(input.state).toBe("idle");
    expect(await input.stop()).toBeNull();
    expect(ttsApi.asrTranscribe).toHaveBeenCalledTimes(1);
  });

  it.each(["permission", "network", "empty"])("%s 失败后可以原地重试", async (failure) => {
    if (failure === "permission")
      getUserMedia.mockRejectedValueOnce(new DOMException("denied", "NotAllowedError"));
    if (failure === "network")
      vi.mocked(ttsApi.asrTranscribe).mockRejectedValueOnce(new Error("offline"));
    if (failure === "empty") vi.mocked(ttsApi.asrTranscribe).mockResolvedValueOnce({ text: " " });
    await input.start();
    if (failure !== "permission") await input.stop();
    expect(callbacks.onErrorKey).toHaveBeenCalledTimes(1);
    expect(input.state).toBe("idle");
    expect(await input.start()).toBe(true);
    await input.stop();
    expect(callbacks.onTranscript.mock.calls).toEqual([["识别文字"]]);
  });

  it.each(["release", "cancel"])("等待授权时 %s，迟到的麦克风流不启动录音", async (action) => {
    let resolve!: (stream: ReturnType<typeof makeStream>) => void;
    getUserMedia.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const pending = input.start();
    expect(input.state).toBe("starting");
    expect(await input.start()).toBe(false);
    if (action === "release") await input.stop();
    else input.cancel();
    resolve(stream);
    expect(await pending).toBe(false);
    expect(recorders).toHaveLength(0);
    expect(stream.getTracks()[0].stop).toHaveBeenCalledTimes(1);
    expect(callbacks.onTranscript).not.toHaveBeenCalled();
    expect(input.state).toBe("idle");
  });

  it("转写中取消会中断请求并丢弃迟到结果", async () => {
    let resolve!: (result: { text: string }) => void;
    vi.mocked(ttsApi.asrTranscribe).mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    await input.start();
    const pending = input.stop();
    await vi.advanceTimersByTimeAsync(0);
    const signal = vi.mocked(ttsApi.asrTranscribe).mock.calls[0][1];
    expect(signal?.aborted).toBe(false);
    input.cancel();
    expect(signal?.aborted).toBe(true);
    resolve({ text: "迟到文字" });
    expect(await pending).toBeNull();
    expect(callbacks.onTranscript).not.toHaveBeenCalled();
    expect(callbacks.onErrorKey).not.toHaveBeenCalled();
  });

  it("WAV 转换中取消，不发起转写请求", async () => {
    let resolve!: (blob: Blob) => void;
    vi.mocked(blobToWav).mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    await input.start();
    const pending = input.stop();
    await vi.advanceTimersByTimeAsync(0);
    input.cancel();
    resolve(new Blob(["wav"]));
    await pending;
    expect(ttsApi.asrTranscribe).not.toHaveBeenCalled();
  });

  it("设备启动失败也会释放已获得的麦克风", async () => {
    FakeRecorder.failStart = true;
    expect(await input.start()).toBe(false);
    expect(stream.getTracks()[0].stop).toHaveBeenCalledTimes(1);
    expect(input.state).toBe("idle");
  });

  it("取消旧录音后重新开始，旧转写不能填入新草稿", async () => {
    let resolve!: (result: { text: string }) => void;
    vi.mocked(ttsApi.asrTranscribe).mockReturnValueOnce(
      new Promise((r) => {
        resolve = r;
      }),
    );
    await input.start();
    const old = input.stop();
    await vi.advanceTimersByTimeAsync(0);
    input.cancel();
    await input.start();
    resolve({ text: "旧会话文字" });
    await old;
    expect(input.state).toBe("recording");
    await input.stop();
    expect(callbacks.onTranscript.mock.calls).toEqual([["识别文字"]]);
  });
});
