/**
 * QuickAskBar 纯逻辑测试（M-D D3）：渲染判定与文案映射
 * （仓库测试约定：纯函数直测，渲染断言留给 GUI 实测）。
 */
import { describe, expect, it } from "vitest";
import { quickReplyLabel, shouldShowQuickBar } from "./SpeechBubbleArea";

describe("shouldShowQuickBar（快速操作条渲染判定）", () => {
  it("null → 不渲染", () => {
    expect(shouldShowQuickBar(null)).toBe(false);
  });

  it("ask + quickReplies → 渲染", () => {
    expect(shouldShowQuickBar({ action: "ask", quickReplies: ["later", "dismiss"] })).toBe(true);
  });

  it("speak（无 quickReplies）→ 不渲染", () => {
    expect(shouldShowQuickBar({ action: "speak", quickReplies: [] })).toBe(false);
  });
});

describe("quickReplyLabel（按钮文案）", () => {
  it("later=稍后 / dismiss=不用提醒", () => {
    expect(quickReplyLabel("later")).toBe("稍后");
    expect(quickReplyLabel("dismiss")).toBe("不用提醒");
  });
});
