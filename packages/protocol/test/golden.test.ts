/**
 * 协议双端一致性测试（TS 侧）：黄金样例逐帧校验。
 *
 * 黄金样例为双端共享夹具（docs/specs/monorepo-structure.md §4）；
 * Python 侧对应测试：server/tests/test_protocol_golden.py。
 * testdata/ 下所有 *.jsonl 自动纳入（M1-S4 起目录扫描）。
 */
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  COMMAND_TYPES,
  EVENT_TYPES,
  PROTOCOL_VERSION,
  type Envelope,
  type TextDeltaData,
  type TextEndData,
  type ToolConfirmData,
} from "../src/index";

const GOLDEN_DIR = fileURLToPath(new URL("../testdata", import.meta.url));
const goldenFiles = readdirSync(GOLDEN_DIR).filter((f) => f.endsWith(".jsonl"));

interface RawFrame {
  v: string;
  type: string;
  id: string;
  ts: number;
  data: Record<string, unknown>;
}

function loadFrames(name: string): RawFrame[] {
  return readFileSync(`${GOLDEN_DIR}/${name}`, "utf-8")
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .map((line) => JSON.parse(line) as RawFrame);
}

const KNOWN_TYPES = new Set<string>([
  ...Object.values(COMMAND_TYPES),
  ...Object.values(EVENT_TYPES),
]);

it("黄金样例文件齐备：工具回合 + 危险工具确认流", () => {
  expect(goldenFiles).toContain("turn-with-tool-call.jsonl");
  expect(goldenFiles).toContain("turn-with-tool-confirm.jsonl");
});

for (const file of goldenFiles) {
  const frames = loadFrames(file);

  describe(`协议黄金样例 ${file}`, () => {
    it("每帧信封结构合法且 type 已注册", () => {
      for (const frame of frames) {
        expect(frame.v).toBe(PROTOCOL_VERSION);
        expect(KNOWN_TYPES.has(frame.type)).toBe(true);
        expect(typeof frame.id).toBe("string");
        expect(frame.id.length).toBeGreaterThan(0);
        expect(typeof frame.ts).toBe("number");
        expect(typeof frame.data).toBe("object");
      }
    });

    it("回合时序：hello → hello_ack → … → run.finished(complete)", () => {
      expect(frames[0].type).toBe(COMMAND_TYPES.Hello);
      expect(frames[1].type).toBe(EVENT_TYPES.HelloAck);
      expect(frames.some((f) => f.type === COMMAND_TYPES.ChatSend)).toBe(true);
      const last = frames[frames.length - 1];
      expect(last.type).toBe(EVENT_TYPES.RunFinished);
      expect(last.data.reason).toBe("complete");
    });

    it("text.delta 拼接等于 text.end.fullText（流式完整性）", () => {
      const deltas = frames
        .filter((f) => f.type === EVENT_TYPES.TextDelta)
        .map((f) => (f as unknown as Envelope<TextDeltaData>).data.delta);
      const fullTexts = frames
        .filter((f) => f.type === EVENT_TYPES.TextEnd)
        .map((f) => (f as unknown as Envelope<TextEndData>).data.fullText);
      expect(fullTexts).toHaveLength(1);
      expect(deltas.join("")).toBe(fullTexts[0]);
    });

    it("确认流不变量：requiresConfirmation 与 tool.confirm 一一对应", () => {
      const requires = frames
        .filter((f) => f.type === EVENT_TYPES.ToolCallStart && f.data.requiresConfirmation === true)
        .map((f) => f.data.toolCallId as string);
      const confirms = new Map(
        frames
          .filter((f) => f.type === COMMAND_TYPES.ToolConfirm)
          .map((f) => [f.data.toolCallId as string, f.data as unknown as ToolConfirmData] as const),
      );
      expect([...confirms.keys()].sort()).toEqual([...requires].sort());
      for (const [toolCallId, confirm] of confirms) {
        const end = frames.find(
          (f) => f.type === EVENT_TYPES.ToolCallEnd && f.data.toolCallId === toolCallId,
        );
        expect(end).toBeDefined();
        expect(end?.data.status).toBe(confirm.decision === "deny" ? "denied" : "success");
      }
    });
  });
}

it("前向兼容：未知 type 应被消费方跳过", () => {
  const future: RawFrame = {
    v: PROTOCOL_VERSION,
    type: "future.event",
    id: "x",
    ts: 0,
    data: {},
  };
  // 消费规则（协议 §1.3）：不在已知集合中的 type 直接忽略
  expect(KNOWN_TYPES.has(future.type)).toBe(false);
});
