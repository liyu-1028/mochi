/**
 * openExternal 纯函数测试：外链协议白名单（测试报告 2026-08-06 问题 1）。
 */
import { describe, expect, it } from "vitest";
import { isSafeExternalUrl } from "./openExternal";

describe("isSafeExternalUrl", () => {
  it("http/https 链接放行", () => {
    expect(isSafeExternalUrl("https://mochi.ai")).toBe(true);
    expect(isSafeExternalUrl("http://example.com/docs?a=1#b")).toBe(true);
  });

  it("非 http(s) 协议一律拒绝（模型输出链接不可信）", () => {
    expect(isSafeExternalUrl("javascript:alert(1)")).toBe(false);
    expect(isSafeExternalUrl("file:///etc/passwd")).toBe(false);
    expect(isSafeExternalUrl("mailto:a@b.com")).toBe(false);
    expect(isSafeExternalUrl("tauri://localhost/index.html")).toBe(false);
  });

  it("空串与非法 URL 拒绝且不抛错", () => {
    expect(isSafeExternalUrl("")).toBe(false);
    expect(isSafeExternalUrl("not a url")).toBe(false);
    expect(isSafeExternalUrl("https://")).toBe(false);
  });
});
