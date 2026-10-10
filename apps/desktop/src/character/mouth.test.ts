/**
 * 口型驱动单测（功能清单 2.3）。纯函数，node 环境。
 */
import { describe, expect, it } from "vitest";
import { MOUTH_CLOSED, MOUTH_DECAY_WINDOW_MS, onDelta, stepMouth, volumeToOpen } from "./mouth";

describe("onDelta：delta 到达触发张嘴", () => {
  it("单字 delta 轻张，长 delta 满张（上限 1）", () => {
    expect(onDelta(MOUTH_CLOSED, "你").target).toBeCloseTo(0.6);
    expect(onDelta(MOUTH_CLOSED, "你好呀，我是").target).toBe(1);
  });

  it("每次 delta 重置衰减窗口", () => {
    const s = onDelta(MOUTH_CLOSED, "你");
    expect(s.decayMs).toBe(MOUTH_DECAY_WINDOW_MS);
  });
});

describe("stepMouth：窗口内保持，窗口外平滑闭合", () => {
  it("窗口内开度向目标逼近", () => {
    let s = onDelta(MOUTH_CLOSED, "你好呀"); // target 1
    s = stepMouth(s, 16);
    expect(s.open).toBeGreaterThan(0.3);
    expect(s.decayMs).toBe(MOUTH_DECAY_WINDOW_MS - 16);
  });

  it("连续 delta 期间保持张嘴", () => {
    let s = onDelta(MOUTH_CLOSED, "你好");
    for (let i = 0; i < 5; i++) {
      s = stepMouth(s, 30);
      s = onDelta(s, "世"); // 每 30ms 一个新 delta，重置窗口
    }
    expect(s.open).toBeGreaterThan(0.5);
  });

  it("delta 停止后约 200ms 内平滑闭合到 0", () => {
    let s = onDelta(MOUTH_CLOSED, "你好呀");
    s = stepMouth(s, 16);
    s = stepMouth(s, MOUTH_DECAY_WINDOW_MS); // 耗尽窗口
    for (let i = 0; i < 30; i++) s = stepMouth(s, 16); // ~500ms
    expect(s.open).toBe(0);
  });

  it("闭合过程单调递减（无突变）", () => {
    let s = onDelta(MOUTH_CLOSED, "你好呀");
    s = stepMouth(s, 16);
    s = stepMouth(s, MOUTH_DECAY_WINDOW_MS);
    let prev = s.open;
    for (let i = 0; i < 10 && s.open > 0; i++) {
      s = stepMouth(s, 16);
      expect(s.open).toBeLessThanOrEqual(prev);
      prev = s.open;
    }
  });
});

describe("volumeToOpen：音量驱动口型（2.7，M1-S2）", () => {
  it("线性放大封顶，非法值夹紧", () => {
    expect(volumeToOpen(0)).toBe(0);
    expect(volumeToOpen(0.5)).toBeCloseTo(0.8);
    expect(volumeToOpen(1)).toBe(1);
    expect(volumeToOpen(2)).toBe(1);
    expect(volumeToOpen(-1)).toBe(0);
  });
});
