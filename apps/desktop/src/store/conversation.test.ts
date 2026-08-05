/**
 * conversation store 归约测试：协议事件 → UI 状态。
 */
import type { ServerEvent } from "@mochi/protocol";
import { beforeEach, describe, expect, it } from "vitest";
import {
  MAX_IN_MEMORY_MESSAGES,
  appendCapped,
  historyToMessages,
  useConversation,
} from "./conversation";
import type { ChatMessage } from "./conversation";

function ev(type: string, data: Record<string, unknown>): ServerEvent {
  return { v: "0.1", type, id: "t", ts: 0, data } as unknown as ServerEvent;
}

function streamAssistant(runId: string, messageId: string, chunks: string[]) {
  const { applyEvent } = useConversation.getState();
  applyEvent(ev("run.started", { runId, sessionId: "s" }));
  applyEvent(ev("text.start", { runId, messageId, role: "assistant" }));
  for (const delta of chunks) {
    applyEvent(ev("text.delta", { runId, messageId, delta }));
  }
  applyEvent(ev("text.end", { runId, messageId, fullText: chunks.join("") }));
  applyEvent(ev("run.finished", { runId, reason: "complete" }));
}

beforeEach(() => {
  useConversation.setState({
    status: "disconnected",
    characterState: "idle",
    emotion: null,
    messages: [],
    activeRunId: null,
    notice: null,
    lastTextDeltaAt: 0,
    lastTextDelta: "",
    isSpeaking: false,
  });
});

describe("文本流归约", () => {
  it("text.start/delta/end 归约为单条 assistant 消息", () => {
    streamAssistant("r1", "m1", ["你好，", "我是 Mochi"]);

    const { messages } = useConversation.getState();
    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({
      id: "m1",
      role: "assistant",
      text: "你好，我是 Mochi",
      streaming: false,
    });
  });

  it("口型驱动信号：delta 刷新时间戳与内容，start/end 切换 isSpeaking（2.3）", () => {
    const { applyEvent } = useConversation.getState();
    applyEvent(ev("text.start", { runId: "r1", messageId: "m1", role: "assistant" }));
    expect(useConversation.getState().isSpeaking).toBe(true);

    applyEvent({ ...ev("text.delta", { runId: "r1", messageId: "m1", delta: "你" }), ts: 111 });
    let s = useConversation.getState();
    expect(s.lastTextDeltaAt).toBe(111);
    expect(s.lastTextDelta).toBe("你");

    applyEvent({ ...ev("text.delta", { runId: "r1", messageId: "m1", delta: "好呀" }), ts: 152 });
    s = useConversation.getState();
    expect(s.lastTextDeltaAt).toBe(152);
    expect(s.lastTextDelta).toBe("好呀");

    applyEvent(ev("text.end", { runId: "r1", messageId: "m1", fullText: "你好呀" }));
    expect(useConversation.getState().isSpeaking).toBe(false);
  });

  it("流式过程中 streaming=true，text.end 后置 false", () => {
    const { applyEvent } = useConversation.getState();
    applyEvent(ev("text.start", { runId: "r1", messageId: "m1", role: "assistant" }));
    expect(useConversation.getState().messages[0].streaming).toBe(true);

    applyEvent(ev("text.delta", { runId: "r1", messageId: "m1", delta: "片段" }));
    expect(useConversation.getState().messages[0].text).toBe("片段");

    applyEvent(ev("text.end", { runId: "r1", messageId: "m1", fullText: "片段" }));
    expect(useConversation.getState().messages[0].streaming).toBe(false);
  });

  it("用户消息与 assistant 消息按序共存", () => {
    useConversation.getState().addUserMessage("你好");
    streamAssistant("r1", "m1", ["嗨"]);

    const { messages } = useConversation.getState();
    expect(messages.map((m) => m.role)).toEqual(["user", "assistant"]);
  });
});

describe("角色状态与情绪", () => {
  it("state.change 更新 characterState", () => {
    useConversation.getState().applyEvent(ev("state.change", { state: "talking" }));
    expect(useConversation.getState().characterState).toBe("talking");
  });

  it("emotion 更新情绪标签", () => {
    useConversation.getState().applyEvent(ev("emotion", { emotion: "happy", intensity: 0.6 }));
    expect(useConversation.getState().emotion).toBe("happy");
  });
});

describe("回合与错误", () => {
  it("run.started 记录 activeRunId；run.finished 清空", () => {
    const { applyEvent } = useConversation.getState();
    applyEvent(ev("run.started", { runId: "r9", sessionId: "s" }));
    expect(useConversation.getState().activeRunId).toBe("r9");

    applyEvent(ev("run.finished", { runId: "r9", reason: "complete" }));
    expect(useConversation.getState().activeRunId).toBeNull();
  });

  it("run.error 写入可读提示", () => {
    useConversation.getState().applyEvent(
      ev("run.error", {
        runId: "r9",
        error: { code: "ERR_INTERNAL", message: "出了点状况", retryable: true },
      }),
    );
    expect(useConversation.getState().notice).toBe("出了点状况");
  });

  it("run.error 有 hint 时优先展示引导文案（6.7）", () => {
    useConversation.getState().applyEvent(
      ev("run.error", {
        runId: "r9",
        error: {
          code: "ERR_MODEL_AUTH",
          message: "模型授权失败",
          retryable: false,
          hint: "请检查 API Key 是否正确",
        },
      }),
    );
    expect(useConversation.getState().notice).toBe("请检查 API Key 是否正确");
  });

  it("未知事件类型忽略（前向兼容）", () => {
    const before = useConversation.getState();
    useConversation.getState().applyEvent(ev("future.event", { anything: 1 }));
    const after = useConversation.getState();
    expect(after.messages).toEqual(before.messages);
    expect(after.characterState).toBe(before.characterState);
    expect(after.activeRunId).toBe(before.activeRunId);
  });
});

describe("内存上限（M1-S1，4.3/4.4）", () => {
  const msg = (id: string): ChatMessage => ({ id, role: "user", text: id, streaming: false });

  it("appendCapped 未超上限时全量保留", () => {
    const result = appendCapped([msg("a"), msg("b")], msg("c"), 5);
    expect(result.map((m) => m.id)).toEqual(["a", "b", "c"]);
  });

  it("appendCapped 超上限时裁掉最旧、保留最近", () => {
    const result = appendCapped([msg("a"), msg("b"), msg("c")], msg("d"), 3);
    expect(result.map((m) => m.id)).toEqual(["b", "c", "d"]);
  });

  it("addUserMessage 累积超过上限后自动裁剪", () => {
    const { addUserMessage } = useConversation.getState();
    for (let i = 0; i < MAX_IN_MEMORY_MESSAGES + 5; i++) {
      useConversation.getState().addUserMessage(`第 ${i} 句`);
    }
    const { messages } = useConversation.getState();
    expect(messages).toHaveLength(MAX_IN_MEMORY_MESSAGES);
    expect(messages[0].text).toBe(`第 5 句`); // 最旧 5 条被裁掉
    expect(messages[messages.length - 1].text).toBe(`第 ${MAX_IN_MEMORY_MESSAGES + 4} 句`);
    void addUserMessage;
  });
});

describe("历史回显（M1-S1，4.3）", () => {
  it("historyToMessages 映射后端历史为 UI 消息", () => {
    const history = [
      { role: "user" as const, content: "你好", ts: 100 },
      { role: "assistant" as const, content: "嗨", ts: 101 },
    ];
    const mapped = historyToMessages(history);
    expect(mapped).toHaveLength(2);
    expect(mapped[0]).toMatchObject({ role: "user", text: "你好", streaming: false });
    expect(mapped[1]).toMatchObject({ role: "assistant", text: "嗨", streaming: false });
    expect(mapped[0].id).not.toEqual(mapped[1].id);
  });

  it("historyToMessages 为历史消息打 fromHistory 标记（气泡区据此过滤闪现）", () => {
    const mapped = historyToMessages([{ role: "assistant", content: "旧回复", ts: 5 }]);
    expect(mapped[0].fromHistory).toBe(true);
  });

  it("hydrateHistory 在空白时回显历史", () => {
    useConversation
      .getState()
      .hydrateHistory(historyToMessages([{ role: "user", content: "上一轮的话", ts: 1 }]));
    expect(useConversation.getState().messages).toHaveLength(1);
    expect(useConversation.getState().messages[0].text).toBe("上一轮的话");
  });

  it("hydrateHistory 已有消息时不覆盖（重连不重复）", () => {
    useConversation.getState().addUserMessage("本轮消息");
    useConversation
      .getState()
      .hydrateHistory(historyToMessages([{ role: "user", content: "历史", ts: 1 }]));
    const { messages } = useConversation.getState();
    expect(messages).toHaveLength(1);
    expect(messages[0].text).toBe("本轮消息");
  });
});
