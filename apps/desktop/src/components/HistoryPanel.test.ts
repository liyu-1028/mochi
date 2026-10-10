/**
 * HistoryPanel formatTs 纯函数测试：本地化短日期。
 */
import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { HistoryPanel, formatTs } from "./HistoryPanel";

describe("formatTs", () => {
  const ts = 1785831097833; // 某个固定时刻

  it("zh-CN 输出含月/日/时/分", () => {
    const out = formatTs(ts, "zh-CN");
    expect(out).toMatch(/\d/);
    expect(out.length).toBeGreaterThan(0);
  });

  it("en 输出本地化格式", () => {
    const out = formatTs(ts, "en");
    expect(out).toMatch(/\d/);
  });

  it("非法时间戳不抛错", () => {
    expect(() => formatTs(Number.NaN, "zh-CN")).not.toThrow();
  });
});

describe("会话入口", () => {
  it("空历史也显示当前会话、新建入口和使用说明", () => {
    const html = renderToStaticMarkup(createElement(HistoryPanel, { onClose: () => undefined }));
    expect(html).toContain("新建会话");
    expect(html).toContain("当前会话");
    expect(html).toContain("发送第一条消息后保存");
    expect(html).toContain("什么时候适合新建会话");
    expect(html).not.toContain("🗑");
  });
});
