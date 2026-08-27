/**
 * 纯函数测试：summarizeArgs（确认框参数摘要）与 formatElapsed（6.6 运行计时）。
 * 组件渲染与三键交互属 GUI 实测范围（记忆：GUI 特性须终端验证）。
 */
import { describe, expect, it } from "vitest";
import { formatElapsed, summarizeArgs } from "./ToolActivity";

describe("summarizeArgs", () => {
  it("空参数 → 空串", () => {
    expect(summarizeArgs({})).toBe("");
  });

  it("常规键值对逐个拼接", () => {
    expect(summarizeArgs({ path: "/tmp/a.txt", mode: "w" })).toBe("path=/tmp/a.txt  mode=w");
  });

  it("超过 3 个键 → 省略号收尾", () => {
    const out = summarizeArgs({ a: "1", b: "2", c: "3", d: "4" });
    expect(out.endsWith("…")).toBe(true);
    expect(out).toContain("a=1");
    expect(out).not.toContain("d=4");
  });

  it("单值超 40 字截断", () => {
    const long = "x".repeat(60);
    const out = summarizeArgs({ content: long });
    expect(out).toBe(`content=${"x".repeat(40)}…`);
  });

  it("非字符串值 JSON 化", () => {
    expect(summarizeArgs({ count: 3, flags: { deep: true } })).toBe('count=3  flags={"deep":true}');
  });

  it("总长超 80 字整体截断", () => {
    const out = summarizeArgs({
      a: "y".repeat(50),
      b: "y".repeat(50),
    });
    expect(out.length).toBe(81); // 80 字 + …
    expect(out.endsWith("…")).toBe(true);
  });
});

describe("formatElapsed（6.6 运行计时）", () => {
  it("秒级展示", () => {
    expect(formatElapsed(0, 0)).toBe("0s");
    expect(formatElapsed(1_000, 4_999)).toBe("3s");
  });

  it("≥60s 转 m:ss", () => {
    expect(formatElapsed(0, 61_000)).toBe("1:01");
    expect(formatElapsed(0, 600_000)).toBe("10:00");
  });

  it("负值/乱序兜底 0s", () => {
    expect(formatElapsed(5_000, 1_000)).toBe("0s");
  });
});
