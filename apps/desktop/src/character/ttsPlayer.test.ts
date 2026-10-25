import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TtsPlayer } from "./ttsPlayer";

const source = () => ({
  connect: vi.fn(),
  start: vi.fn(),
  stop: vi.fn(),
  buffer: null,
  onended: null,
});
let context: {
  state: string;
  destination: object;
  decodeAudioData: ReturnType<typeof vi.fn>;
  createBufferSource: ReturnType<typeof vi.fn>;
  createAnalyser: ReturnType<typeof vi.fn>;
  createGain: ReturnType<typeof vi.fn>;
};

beforeEach(() => {
  context = {
    state: "running",
    destination: {},
    decodeAudioData: vi.fn().mockResolvedValue({ duration: 1 }),
    createBufferSource: vi.fn(source),
    createAnalyser: vi.fn(() => ({ connect: vi.fn(), fftSize: 0 })),
    createGain: vi.fn(() => ({ connect: vi.fn(), gain: { value: 1 } })),
  };
  vi.stubGlobal("AudioContext", function () {
    return context;
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("异步解码与停止", () => {
  it("解码期间 stop，旧音频不能开始播放", async () => {
    let resolve!: (value: { duration: number }) => void;
    context.decodeAudioData.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const player = new TtsPlayer();
    const pending = player.play(new Blob(["audio"]));
    await vi.waitFor(() => expect(context.decodeAudioData).toHaveBeenCalled());
    player.stop();
    resolve({ duration: 1 });
    expect(await pending).toBe(false);
    expect(context.createBufferSource).not.toHaveBeenCalled();
    expect(player.playing).toBe(false);
  });

  it("旧解码失败不能清掉后来已开始的播放", async () => {
    let reject!: (reason: Error) => void;
    context.decodeAudioData.mockReturnValueOnce(
      new Promise((_resolve, r) => {
        reject = r;
      }),
    );
    const player = new TtsPlayer();
    const old = player.play(new Blob(["old"]));
    await vi.waitFor(() => expect(context.decodeAudioData).toHaveBeenCalledTimes(1));
    expect(await player.play(new Blob(["new"]))).toBe(true);
    reject(new Error("old decode failed"));
    expect(await old).toBe(false);
    expect(player.playing).toBe(true);
    player.stop();
  });

  it("音频上下文未解锁时报告不可播放，供调用方转入文字节拍", async () => {
    context.state = "suspended";
    const player = new TtsPlayer();
    expect(await player.play(new Blob(["audio"]))).toBe(false);
    expect(context.createBufferSource).not.toHaveBeenCalled();
  });
});
