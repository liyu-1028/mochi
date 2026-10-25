import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { emit, listen, type EventCallback } from "@tauri-apps/api/event";

vi.mock("@tauri-apps/api/event", () => ({ emit: vi.fn(), listen: vi.fn() }));

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.stubGlobal("window", { __TAURI_INTERNALS__: {} });
});
afterEach(() => vi.unstubAllGlobals());

describe("语音设置跨窗口通知", () => {
  it("发送窗口本地只通知一次，接收窗口不重复广播", async () => {
    const receivers: Array<EventCallback<unknown>> = [];
    vi.mocked(listen).mockImplementation(async (_event, handler) => {
      receivers.push(handler);
      return () => {};
    });
    vi.mocked(emit).mockImplementation(async (_event, payload) => {
      for (const receive of receivers) receive({ event: _event, id: 1, payload });
    });
    const main = await import("./voiceEvents");
    await main.initVoiceEventListener();
    await main.initVoiceEventListener();
    vi.resetModules();
    const panel = await import("./voiceEvents");
    await panel.initVoiceEventListener();
    const mainChange = vi.fn();
    const panelChange = vi.fn();
    main.voiceEvents.addEventListener("voice-changed", mainChange);
    panel.voiceEvents.addEventListener("voice-changed", panelChange);
    panel.notifyVoiceChanged();
    expect(mainChange).toHaveBeenCalledTimes(1);
    expect(panelChange).toHaveBeenCalledTimes(1);
    expect(emit).toHaveBeenCalledTimes(1);
    expect(listen).toHaveBeenCalledTimes(2);
  });

  it("浏览器模式仅本地通知，不调用 Tauri", async () => {
    vi.stubGlobal("window", {});
    const events = await import("./voiceEvents");
    const changed = vi.fn();
    events.voiceEvents.addEventListener("voice-changed", changed);
    await events.initVoiceEventListener();
    events.notifyVoiceChanged();
    expect(changed).toHaveBeenCalledTimes(1);
    expect(listen).not.toHaveBeenCalled();
    expect(emit).not.toHaveBeenCalled();
  });
});
