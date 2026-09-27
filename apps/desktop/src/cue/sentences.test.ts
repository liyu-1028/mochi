/**
 * sentences.ts 分句规则测试（M-C）：与服务端 cue_extractor 同一规范的客户端实现。
 * 服务端对应用例：server/tests/test_cue_extractor.py（分句边界编号）。
 */
import { describe, expect, it } from "vitest";
import { sentenceStartTimes, splitSentences } from "./sentences";

describe("splitSentences", () => {
  it("中英文终止符切分，终止符不含在句内", () => {
    const spans = splitSentences("第一句。Second! 第三句？");
    expect(spans).toHaveLength(3);
    expect(spans.map((s) => "第一句。Second! 第三句？".slice(s.start, s.end))).toEqual([
      "第一句",
      "Second",
      " 第三句",
    ]);
  });

  it("连续终止符折叠为一个边界", () => {
    expect(splitSentences("好！！真的吗？！嗯")).toHaveLength(3);
  });

  it("换行是终止符", () => {
    expect(splitSentences("第一行\n第二行")).toHaveLength(2);
  });

  it("末尾无终止符的残余也是一句", () => {
    expect(splitSentences("一句。尾巴")).toHaveLength(2);
  });

  it("空文本 → 无句子", () => {
    expect(splitSentences("")).toEqual([]);
  });
});

describe("sentenceStartTimes", () => {
  it("按字符占比在真实音频时长上分布", () => {
    // "ab。cd！" 共 6 字符：句2 起点 = 3/6 × 1000ms = 500
    const starts = sentenceStartTimes("ab。cd！", 1000);
    expect(starts).toEqual([0, 500]);
  });

  it("无音频时长（fallback 引擎）按字符数估算且不低于下限", () => {
    const starts = sentenceStartTimes("短。句", null);
    expect(starts[0]).toBe(0);
    expect(starts[1]).toBeGreaterThan(0);
    expect(starts[1]).toBeLessThan(1200); // 估算上限受 1.2s 下限约束
  });

  it("空文本 → [0]（speech_start 与第 1 句重合）", () => {
    expect(sentenceStartTimes("", 1000)).toEqual([0]);
  });
});
