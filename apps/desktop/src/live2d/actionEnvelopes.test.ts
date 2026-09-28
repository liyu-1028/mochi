/**
 * actionEnvelopes 测试（M-A）：确定性、幅度预算、时序收敛。
 *
 * 幅度分级预算（2026-09-28 用户实测反馈后调整）：
 * - 闲置复用动作（背景生命感）：2.8 克制档 ≤8px/0.12rad；
 * - 反馈动作（用户应答）：≤18px/0.2rad——可感知档。
 * 全部包络在其 durationMs 之后必须返回 null（one-shot 结束语义）。
 */
import { describe, expect, it } from "vitest";
import { ACTION_ENVELOPES } from "./actionEnvelopes";
import { SEMANTIC_ACTIONS } from "@mochi/protocol";

const IDLE_BUDGET = { dx: 8, dy: 8, rot: 0.12 };
const FEEDBACK_BUDGET = { dx: 18, dy: 18, rot: 0.2 };
const IDLE_REUSED = new Set(["look_around", "stretch", "doze"]);

function budgetOf(id: string) {
  return IDLE_REUSED.has(id) ? IDLE_BUDGET : FEEDBACK_BUDGET;
}

describe("ACTION_ENVELOPES 注册表", () => {
  it("覆盖语义词表全集（协议规范 §11，12 项）", () => {
    for (const id of SEMANTIC_ACTIONS) {
      expect(ACTION_ENVELOPES[id], `缺少包络：${id}`).toBeDefined();
    }
  });

  it("每个包络 durationMs > 0（idle_neutral 除外，其为 0ms 占位）", () => {
    for (const [id, env] of Object.entries(ACTION_ENVELOPES)) {
      if (id === "idle_neutral") {
        expect(env.durationMs).toBe(0);
      } else {
        expect(env.durationMs, id).toBeGreaterThan(0);
      }
    }
  });
});

describe("包络行为", () => {
  it("确定性：同一 elapsed 两次调用结果一致", () => {
    for (const env of Object.values(ACTION_ENVELOPES)) {
      const a = env.apply(env.durationMs / 3);
      const b = env.apply(env.durationMs / 3);
      expect(a).toEqual(b);
    }
  });

  it("幅度分级预算：闲置复用 ≤8px/0.12rad，反馈动作 ≤18px/0.2rad", () => {
    for (const [id, env] of Object.entries(ACTION_ENVELOPES)) {
      const b = budgetOf(id);
      for (let t = 0; t < env.durationMs; t += 16) {
        const d = env.apply(t);
        if (!d) continue;
        expect(Math.abs(d.dx), `${id}@${t}ms dx`).toBeLessThanOrEqual(b.dx);
        expect(Math.abs(d.dy), `${id}@${t}ms dy`).toBeLessThanOrEqual(b.dy);
        expect(Math.abs(d.rotation), `${id}@${t}ms rotation`).toBeLessThanOrEqual(b.rot);
      }
    }
  });

  it("one-shot 结束语义：durationMs 时刻及以后返回 null（idle_neutral 恒 null）", () => {
    for (const [id, env] of Object.entries(ACTION_ENVELOPES)) {
      expect(env.apply(env.durationMs), `${id}@end`).toBeNull();
      expect(env.apply(env.durationMs + 1000), `${id}@end+1s`).toBeNull();
      expect(env.apply(-1), `${id}@negative`).toBeNull();
    }
  });

  it("起始与结束均收敛到零附近（不突兀起势/截断）", () => {
    for (const [id, env] of Object.entries(ACTION_ENVELOPES)) {
      if (id === "idle_neutral") continue;
      const start = env.apply(0);
      const nearEnd = env.apply(env.durationMs - 1);
      for (const d of [start, nearEnd]) {
        if (!d) continue;
        expect(Math.abs(d.dx) + Math.abs(d.dy) + Math.abs(d.rotation), id).toBeLessThan(0.6);
      }
    }
  });

  it("idle_neutral 恒返回 null（兜底 = 保持当前 loop 原样）", () => {
    const env = ACTION_ENVELOPES.idle_neutral;
    expect(env.apply(0)).toBeNull();
    expect(env.apply(500)).toBeNull();
  });
});
