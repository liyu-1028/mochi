/**
 * 协议双端一致性测试（TS 侧）：常量 vs 共享夹具。
 *
 * 黄金样例机制（docs/specs/monorepo-structure.md §4）覆盖事件帧；
 * 本测试覆盖非帧常量（语义动作注册表，协议规范 §11）。
 * 夹具：testdata/semantic-actions.json；
 * Python 侧对应测试：server/tests/test_protocol_golden.py。
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  ACTION_CHANNELS,
  COMMAND_TYPES,
  CUE_INTERRUPT_POLICIES,
  CUE_SOURCES,
  CUE_SYNC,
  EVENT_TYPES,
  type CompanionIntentData,
  type CompanionSignalData,
  INTENT_ACTIONS,
  INTENT_DECISIONS,
  INTENT_QUICK_REPLIES,
  MESSAGE_SOURCES,
  type RunStartedData,
  SEMANTIC_ACTIONS,
  SIGNAL_KINDS,
  SIGNAL_SALIENCE,
  type TextStartData,
} from "../src/index";

const fixturePath = fileURLToPath(new URL("../testdata/semantic-actions.json", import.meta.url));

interface Fixture {
  semanticActions: string[];
  actionChannels: string[];
}

const fixture = JSON.parse(readFileSync(fixturePath, "utf-8")) as Fixture;

describe("语义动作注册表（协议规范 §11）", () => {
  it("SEMANTIC_ACTIONS 与共享夹具逐项一致（顺序敏感）", () => {
    expect([...SEMANTIC_ACTIONS]).toEqual(fixture.semanticActions);
  });

  it("ACTION_CHANNELS 与共享夹具逐项一致（顺序敏感）", () => {
    expect([...ACTION_CHANNELS]).toEqual(fixture.actionChannels);
  });

  it("词表约束：idle_neutral 必在（全链路兜底终点）、id 均为 snake_case", () => {
    expect(SEMANTIC_ACTIONS).toContain("idle_neutral");
    for (const id of SEMANTIC_ACTIONS) {
      expect(id).toMatch(/^[a-z][a-z0-9_]*$/);
    }
  });
});

describe("character.cue 负载（协议规范 §5.6，M-C）", () => {
  const cueFixturePath = fileURLToPath(new URL("../testdata/character-cue.json", import.meta.url));
  const cueFixture = JSON.parse(readFileSync(cueFixturePath, "utf-8")) as {
    event: { type: string; data: CharacterCueData };
    expectedEnums: Record<string, string[]>;
  };

  it("EVENT_TYPES 含 CharacterCue（character.cue）", () => {
    expect(EVENT_TYPES.CharacterCue).toBe("character.cue");
    expect(cueFixture.event.type).toBe(EVENT_TYPES.CharacterCue);
  });

  it("夹具负载字段与 TS 类型形态一致（结构回归锚点）", () => {
    const data = cueFixture.event.data;
    expect(data.cueId).toBe("c-1a2b3c4d5e6f");
    expect(data.source).toBe("reply");
    expect(data.sync).toBe("sentence_boundary");
    expect(data.sentenceIndex).toBe(2);
    expect(data.channels.face?.emotion).toBe("happy");
    expect(data.channels.body?.actionId).toBe("comfort");
    expect(data.priority).toBe(45);
    expect(data.interruptPolicy).toBe("replace");
    expect(data.ttlMs).toBe(15000);
  });

  it("cue 枚举与夹具 expectedEnums 一致", () => {
    expect([...CUE_SOURCES]).toEqual(cueFixture.expectedEnums.CUE_SOURCES);
    expect([...CUE_SYNC]).toEqual(cueFixture.expectedEnums.CUE_SYNC);
    expect([...CUE_INTERRUPT_POLICIES]).toEqual(cueFixture.expectedEnums.CUE_INTERRUPT_POLICIES);
  });
});

describe("companion.signal 命令（协议 §6.x，M-D）", () => {
  const fixturePath = fileURLToPath(new URL("../testdata/companion-signal.json", import.meta.url));
  const fixture = JSON.parse(readFileSync(fixturePath, "utf-8")) as {
    command: { type: string; data: CompanionSignalData };
    expectedEnums: Record<string, string[] | number[]>;
  };

  it("COMMAND_TYPES 含 CompanionSignal（companion.signal）", () => {
    expect(COMMAND_TYPES.CompanionSignal).toBe("companion.signal");
    expect(fixture.command.type).toBe(COMMAND_TYPES.CompanionSignal);
  });

  it("夹具负载字段与 TS 类型形态一致（结构回归锚点）", () => {
    const data = fixture.command.data;
    expect(typeof data.signalId).toBe("string");
    expect(SIGNAL_KINDS).toContain(data.kind);
    expect(typeof data.occurredAt).toBe("number");
    expect(SIGNAL_SALIENCE).toContain(data.salience);
    expect(typeof data.dedupeKey).toBe("string");
    expect(data.payload).toBeTypeOf("object");
  });

  it("信号/来源枚举与夹具 expectedEnums 一致（顺序敏感）", () => {
    const e = fixture.expectedEnums as Record<string, unknown[]>;
    expect([...SIGNAL_KINDS]).toEqual(e.SIGNAL_KINDS);
    expect([...SIGNAL_SALIENCE]).toEqual(e.SIGNAL_SALIENCE);
    expect([...INTENT_ACTIONS]).toEqual(e.INTENT_ACTIONS);
    expect([...INTENT_QUICK_REPLIES]).toEqual(e.INTENT_QUICK_REPLIES);
    expect([...INTENT_DECISIONS]).toEqual(e.INTENT_DECISIONS);
    expect([...MESSAGE_SOURCES]).toEqual(e.MESSAGE_SOURCES);
  });
});

describe("companion.intent 事件（协议 §5.7，M-D）", () => {
  const fixturePath = fileURLToPath(new URL("../testdata/companion-intent.json", import.meta.url));
  const fixture = JSON.parse(readFileSync(fixturePath, "utf-8")) as {
    event: { type: string; data: CompanionIntentData };
  };

  it("EVENT_TYPES 含 CompanionIntent（companion.intent）", () => {
    expect(EVENT_TYPES.CompanionIntent).toBe("companion.intent");
    expect(fixture.event.type).toBe(EVENT_TYPES.CompanionIntent);
  });

  it("夹具负载字段与 TS 类型形态一致（结构回归锚点）", () => {
    const data = fixture.event.data;
    expect(typeof data.intentId).toBe("string");
    expect(INTENT_ACTIONS).toContain(data.action);
    expect(SIGNAL_KINDS).toContain(data.kind);
    for (const q of data.quickReplies) {
      expect(INTENT_QUICK_REPLIES).toContain(q);
    }
  });
});

describe("proactive 回合序列（source 字段族，M-D §8 决策点 4）", () => {
  const fixturePath = fileURLToPath(
    new URL("../testdata/sequences/proactive-turn.jsonl", import.meta.url),
  );
  const frames = readFileSync(fixturePath, "utf-8")
    .split("\n")
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l) as { type: string; data: Record<string, unknown> });

  it("时序骨架：run.started → text.* → run.finished", () => {
    expect(frames.map((f) => f.type)).toEqual([
      "run.started",
      "text.start",
      "text.delta",
      "text.delta",
      "text.end",
      "run.finished",
    ]);
  });

  it("run/text 事件族逐帧 source=proactive，intentId 关联 companion.intent", () => {
    for (const frame of frames) {
      if (frame.type === "run.started") {
        const data = frame.data as unknown as RunStartedData;
        expect(data.source).toBe("proactive");
        expect(data.intentId).toBe("intent-7a6b5c4d3e2f");
      } else if (frame.type.startsWith("text.")) {
        const data = frame.data as unknown as TextStartData;
        expect(data.source).toBe("proactive");
      }
    }
  });

  it("source 缺省按 user（additive 兼容锚点）", () => {
    const userFrame = { runId: "r", messageId: "m", role: "assistant" };
    expect((userFrame as unknown as TextStartData).source).toBeUndefined();
    expect(MESSAGE_SOURCES).toEqual(["user", "proactive"]);
  });
});
