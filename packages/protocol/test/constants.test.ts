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
import { ACTION_CHANNELS, SEMANTIC_ACTIONS } from "../src/index";

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
