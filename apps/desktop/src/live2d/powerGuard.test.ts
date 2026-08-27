/**
 * powerGuard 纯函数测试（2.6：自动降档/回升/省电钉档/回滞防抖）。
 */
import { describe, expect, it } from "vitest";
import {
  createSampleWindow,
  decorationsPaused,
  effectiveFps,
  nextFpsLevel,
  type FpsLevel,
} from "./powerGuard";

describe("createSampleWindow", () => {
  it("空窗均值 null", () => {
    expect(createSampleWindow().average()).toBeNull();
  });

  it("窗口内均值", () => {
    const w = createSampleWindow(5000);
    w.push(30, 0);
    w.push(50, 1000);
    expect(w.average()).toBe(40);
  });

  it("淘汰窗口外样本", () => {
    const w = createSampleWindow(5000);
    w.push(60, 0);
    w.push(10, 6000);
    w.push(10, 6100);
    expect(w.average()).toBe(10);
  });
});

describe("nextFpsLevel", () => {
  it("省电模式钉最低档", () => {
    expect(nextFpsLevel(0, 5, true)).toBe(2);
    expect(nextFpsLevel(1, 5, true)).toBe(2);
  });

  it("过载（>40ms）逐档降，最低不越界", () => {
    expect(nextFpsLevel(0, 45, false)).toBe(1);
    expect(nextFpsLevel(1, 60, false)).toBe(2);
    expect(nextFpsLevel(2, 100, false)).toBe(2);
  });

  it("空闲（<25ms）逐档回升", () => {
    expect(nextFpsLevel(2, 20, false)).toBe(1);
    expect(nextFpsLevel(1, 10, false)).toBe(0);
    expect(nextFpsLevel(0, 10, false)).toBe(0);
  });

  it("回滞区间（25–40ms）保持不动", () => {
    expect(nextFpsLevel(0, 30, false)).toBe(0);
    expect(nextFpsLevel(1, 35, false)).toBe(1);
    expect(nextFpsLevel(2, 25, false)).toBe(2);
  });

  it("无样本保持", () => {
    expect(nextFpsLevel(1, null, false)).toBe(1);
  });
});

describe("effectiveFps", () => {
  it("档位映射：基准/封 30/钉 15", () => {
    expect(effectiveFps(60, 0)).toBe(60);
    expect(effectiveFps(30, 0)).toBe(30);
    expect(effectiveFps(60, 1)).toBe(30);
    expect(effectiveFps(30, 1)).toBe(30);
    expect(effectiveFps(60, 2)).toBe(15);
  });
});

describe("decorationsPaused", () => {
  it("降档即暂停装饰动画", () => {
    expect(decorationsPaused(0 as FpsLevel)).toBe(false);
    expect(decorationsPaused(1 as FpsLevel)).toBe(true);
    expect(decorationsPaused(2 as FpsLevel)).toBe(true);
  });
});
