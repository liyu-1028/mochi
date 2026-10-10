import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const KEY = "mochi.activeSessionId";
let saved: Map<string, string>;

beforeEach(() => {
  vi.resetModules();
  saved = new Map();
  vi.stubGlobal("window", {
    localStorage: {
      getItem: (key: string) => saved.get(key) ?? null,
      setItem: (key: string, value: string) => saved.set(key, value),
    },
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("会话选择", () => {
  it("没有选择时沿用原有 default 历史", async () => {
    const { useConversation } = await import("./conversation");
    expect(useConversation.getState().activeSessionId).toBe("default");
  });

  it("切换后重启仍选中该会话", async () => {
    const { useConversation } = await import("./conversation");
    useConversation.getState().activateSession("new-chat");
    expect(saved.get(KEY)).toBe("new-chat");
    vi.resetModules();
    const restarted = await import("./conversation");
    expect(restarted.useConversation.getState().activeSessionId).toBe("new-chat");
  });

  it("切换隔离旧回复、工具确认、语音与表演状态", async () => {
    const { useConversation } = await import("./conversation");
    useConversation.getState().addUserMessage("旧话题");
    useConversation.setState({
      activeRunId: "old-run",
      characterState: "talking",
      isSpeaking: true,
      lastSpokenText: "旧回复",
      lastTextEndAt: 123,
      cueRunIds: ["old-run"],
      notice: "旧错误",
      pendingConfirm: {
        toolCallId: "t",
        name: "bash",
        args: {},
        status: "confirming",
        startedAt: 1,
      },
      pendingIntent: {
        intentId: "i",
        action: "ask",
        kind: "break",
        quickReplies: [],
        expiresAt: null,
      },
    });
    useConversation.getState().activateSession("new-chat");
    expect(useConversation.getState()).toMatchObject({
      activeSessionId: "new-chat",
      status: "connecting",
      messages: [],
      activeRunId: null,
      characterState: "idle",
      isSpeaking: false,
      lastSpokenText: null,
      lastTextEndAt: 0,
      pendingCues: [],
      cueRunIds: [],
      notice: null,
      pendingConfirm: null,
      pendingIntent: null,
    });
  });

  it("继续当前会话保留已有回复", async () => {
    const { useConversation } = await import("./conversation");
    useConversation.getState().addUserMessage("继续说");
    const before = useConversation.getState();
    before.activateSession(before.activeSessionId);
    expect(useConversation.getState()).toBe(before);
  });

  it("本地存储不可用时仍可切换", async () => {
    vi.stubGlobal("window", {
      get localStorage() {
        throw new Error("unavailable");
      },
    });
    const { useConversation } = await import("./conversation");
    expect(useConversation.getState().activeSessionId).toBe("default");
    expect(() => useConversation.getState().activateSession("new-chat")).not.toThrow();
    expect(useConversation.getState().activeSessionId).toBe("new-chat");
  });
});
