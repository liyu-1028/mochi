/**
 * pickBubbleStack / computeHideDelay 纯函数测试：
 * 气泡栈最多取最新两条 assistant 回复（更早丢弃、历史回显过滤）。
 */
import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../store/conversation";
import { computeHideDelay, pickBubbleStack } from "./SpeechBubbleArea";

const assistant = (id: string, text = "hi", extra: Partial<ChatMessage> = {}): ChatMessage => ({
  id,
  role: "assistant",
  text,
  streaming: false,
  ...extra,
});

const user = (id: string, text = "q"): ChatMessage => ({
  id,
  role: "user",
  text,
  streaming: false,
});

describe("pickBubbleStack", () => {
  it("空消息列表 → 空栈", () => {
    expect(pickBubbleStack([])).toEqual({ prev: undefined, latest: undefined });
  });

  it("只有 user 消息 → 空栈", () => {
    expect(pickBubbleStack([user("u1"), user("u2")])).toEqual({
      prev: undefined,
      latest: undefined,
    });
  });

  it("仅 1 条 assistant → 只有 latest，无预览", () => {
    const a1 = assistant("a1");
    expect(pickBubbleStack([user("u1"), a1])).toEqual({ prev: undefined, latest: a1 });
  });

  it("2 条 assistant → prev 为第一条、latest 为第二条", () => {
    const a1 = assistant("a1");
    const a2 = assistant("a2");
    expect(pickBubbleStack([user("u1"), a1, user("u2"), a2])).toEqual({ prev: a1, latest: a2 });
  });

  it("3 条 assistant → 取最新两条，最老一条丢弃", () => {
    const a1 = assistant("a1");
    const a2 = assistant("a2");
    const a3 = assistant("a3");
    expect(pickBubbleStack([a1, a2, a3])).toEqual({ prev: a2, latest: a3 });
  });

  it("fromHistory 回显消息不参与组栈", () => {
    const h1 = assistant("h1", "history", { fromHistory: true });
    const a1 = assistant("a1");
    expect(pickBubbleStack([h1, a1])).toEqual({ prev: undefined, latest: a1 });
  });
});

describe("computeHideDelay", () => {
  it("空文本 → 基础 2000ms", () => {
    expect(computeHideDelay("")).toBe(2000);
  });

  it("随字数线性增长（150ms/字）", () => {
    expect(computeHideDelay("十个字的文本一二三四")).toBe(2000 + 10 * 150);
  });

  it("超长文本封顶 15000ms", () => {
    expect(computeHideDelay("长".repeat(200))).toBe(15000);
  });
});
