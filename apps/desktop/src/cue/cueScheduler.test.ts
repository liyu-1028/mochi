/**
 * cueScheduler 测试（M-C C3）：sync 对齐、过期不补演、乱序安全。
 * 全部时序由显式 now 驱动（调度器无定时器），可精确推演。
 */
import type { CharacterCueData } from "@mochi/protocol";
import { describe, expect, it } from "vitest";
import {
  beginSpeech,
  createCueScheduler,
  dueCues,
  endSpeech,
  resetCues,
  submitCue,
} from "./cueScheduler";

function cue(overrides: Partial<CharacterCueData> = {}): CharacterCueData {
  return {
    cueId: "c-1",
    runId: "r-1",
    messageId: "m-1",
    source: "reply",
    channels: { body: { actionId: "comfort" } },
    sync: "sentence_boundary",
    sentenceIndex: 1,
    priority: 45,
    interruptPolicy: "replace",
    ttlMs: 15000,
    ...overrides,
  };
}

/** 测试换算器：直接映射为最小 DirectorCue 形态（组件层闭包的等价物）。 */
const convert = (c: CharacterCueData, channel: "face" | "body", now: number) => ({
  cueId: `${c.cueId}:${channel}`,
  actionId:
    channel === "face"
      ? (c.channels.face?.emotion ?? "neutral")
      : (c.channels.body?.actionId ?? "idle_neutral"),
  channel,
  priority: c.priority,
  interruptPolicy: c.interruptPolicy,
  ttlMs: c.ttlMs,
  cooldownMs: 0,
  durationMs: 1000,
  source: "reply" as const,
  createdAt: now,
});

describe("submitCue", () => {
  it("信封 ts + ttl 已过 → 到达即丢（expired）", () => {
    const s = createCueScheduler();
    // ts=0、ttl=15000 → now=15000 时已过期
    expect(submitCue(s, cue(), 0, 15_000)).toBe("expired");
    expect(s.pending).toHaveLength(0);
  });

  it("有效期内到达 → 排队等待对齐点", () => {
    const s = createCueScheduler();
    expect(submitCue(s, cue(), 0, 100)).toBe("accepted");
    expect(s.pending).toHaveLength(1);
  });
});

describe("sync 对齐", () => {
  it("immediate：到达即到期，不需播报上下文", () => {
    const s = createCueScheduler();
    submitCue(s, cue({ sync: "immediate", cueId: "c-imm" }), 0, 100);
    const due = dueCues(s, 101, convert);
    expect(due).toHaveLength(1);
    expect(due[0].actionId).toBe("comfort");
  });

  it("speech_start：播报开始时到期", () => {
    const s = createCueScheduler();
    submitCue(s, cue({ sync: "speech_start", cueId: "c-ss" }), 0, 100);
    expect(dueCues(s, 200, convert)).toHaveLength(0); // 未播报 → 等待
    beginSpeech(s, "你好。世界。", 1000, 300);
    expect(dueCues(s, 300, convert)).toHaveLength(1); // 播报开始即到期
  });

  it("sentence_boundary：第 N 句起点到期；无该句时钳到末句起点", () => {
    const s = createCueScheduler();
    // "ab。cd！"（6 字符）时长 1000：句1=0、句2=500（相对播报起点 500）
    submitCue(s, cue({ cueId: "c-s1", sentenceIndex: 1 }), 0, 100);
    submitCue(s, cue({ cueId: "c-s2", sentenceIndex: 2 }), 0, 100);
    submitCue(s, cue({ cueId: "c-s9", sentenceIndex: 9 }), 0, 100); // 越界 → 钳到末句
    beginSpeech(s, "ab。cd！", 1000, 500);
    expect(dueCues(s, 500, convert).map((c) => c.cueId)).toEqual(["c-s1:body"]);
    expect(dueCues(s, 999, convert).map((c) => c.cueId)).toEqual([]); // 500+500-1 未到
    expect(dueCues(s, 1000, convert).map((c) => c.cueId)).toEqual(["c-s2:body", "c-s9:body"]);
  });

  it("speech_end：播报结束时到期；endSpeech 提前收口", () => {
    const s = createCueScheduler();
    submitCue(s, cue({ sync: "speech_end", cueId: "c-se" }), 0, 100);
    beginSpeech(s, "你好。", 5000, 200);
    expect(dueCues(s, 1000, convert)).toHaveLength(0);
    endSpeech(s, 1500); // 用户打断 → 播报提前结束
    expect(dueCues(s, 1500, convert)).toHaveLength(1);
  });

  it("face+body 双通道 cue 各发一条，不重复", () => {
    const s = createCueScheduler();
    submitCue(
      s,
      cue({
        sync: "immediate",
        cueId: "c-both",
        channels: { face: { emotion: "happy", intensity: 0.75 }, body: { actionId: "nod" } },
      }),
      0,
      100,
    );
    const due = dueCues(s, 101, convert);
    expect(due.map((c) => c.channel).sort()).toEqual(["body", "face"]);
    expect(dueCues(s, 200, convert)).toHaveLength(0); // 已发不重复
  });
});

describe("过期不补演（验收项）", () => {
  it("排队期间始终未等到对齐点 → ttl 耗尽被巡检丢弃", () => {
    const s = createCueScheduler();
    submitCue(s, cue({ sync: "sentence_boundary", cueId: "c-wait" }), 0, 100); // ttl 15s
    beginSpeech(s, "一句", 60_000, 5000); // 长播报，句1 起点即 5000
    expect(dueCues(s, 6000, convert)).toHaveLength(1); // 正常到期
  });

  it("到期前未播报、超 ttl → 丢弃", () => {
    const s = createCueScheduler();
    submitCue(s, cue({ sync: "speech_start", cueId: "c-never" }), 0, 100);
    expect(dueCues(s, 20_000, convert)).toHaveLength(0); // 超过期巡检 → 丢
    beginSpeech(s, "太迟了。", 1000, 20_100);
    expect(dueCues(s, 20_100, convert)).toHaveLength(0); // 已被丢弃，不补演
  });
});

describe("回合切换", () => {
  it("resetCues 清空排队与播报上下文", () => {
    const s = createCueScheduler();
    submitCue(s, cue({ sync: "immediate" }), 0, 100);
    beginSpeech(s, "x", 100, 100);
    resetCues(s);
    expect(s.pending).toHaveLength(0);
    expect(s.speech).toBeNull();
  });
});
