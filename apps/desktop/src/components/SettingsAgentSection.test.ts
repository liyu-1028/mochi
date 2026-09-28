/**
 * SettingsAgentSection 输入校验纯函数测试（node 环境直测，仓库惯例）。
 */
import { describe, expect, it } from "vitest";
import { parseMaxReplyChars } from "./SettingsAgentSection";

describe("parseMaxReplyChars", () => {
  it("合法：50–4000 整数", () => {
    expect(parseMaxReplyChars("200")).toBe(200);
    expect(parseMaxReplyChars("50")).toBe(50);
    expect(parseMaxReplyChars("4000")).toBe(4000);
  });

  it("非法：越界/非整数/非数字 → null", () => {
    expect(parseMaxReplyChars("49")).toBeNull();
    expect(parseMaxReplyChars("4001")).toBeNull();
    expect(parseMaxReplyChars("200.5")).toBeNull();
    expect(parseMaxReplyChars("abc")).toBeNull();
    expect(parseMaxReplyChars("")).toBeNull();
  });
});
