/**
 * stageDirections（M-F）测试：TTS 剥离口径与服务端 stage_directions.py 一致。
 * 验收锚点：全角成对段与流末残段均剥离；幂等；半角括号不碰。
 */
import { describe, expect, it } from "vitest";
import { stripStageDirections } from "./stageDirections";

describe("stripStageDirections（M-F）", () => {
  it("剥离成对全角括号段", () => {
    expect(stripStageDirections("你好（眨眨眼）世界！")).toBe("你好世界！");
    expect(stripStageDirections("（挥手）开局（点头）收尾")).toBe("开局收尾");
  });

  it("剥离流末未闭合残段", () => {
    expect(stripStageDirections("你好（悄悄")).toBe("你好");
    expect(stripStageDirections("（眨眨眼）嘿！你还在吗（小声")).toBe("嘿！你还在吗");
  });

  it("幂等", () => {
    const once = stripStageDirections("好（笑）！）奇怪（（套）");
    expect(stripStageDirections(once)).toBe(once);
  });

  it("半角括号不碰（代码/数学惯例）", () => {
    expect(stripStageDirections("f(x) = x + 1")).toBe("f(x) = x + 1");
  });

  it("无指示时原样返回", () => {
    expect(stripStageDirections("普通的一句话。")).toBe("普通的一句话。");
  });
});
