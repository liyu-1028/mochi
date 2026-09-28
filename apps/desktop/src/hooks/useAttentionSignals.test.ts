/**
 * evaluateAttentionReport 纯函数测试（M-D D3）。
 * 阈值/断链/回合兜底等边界全表——无定时器、无 DOM。
 */
import { describe, expect, it } from "vitest";
import {
  evaluateAttentionReport,
  FOCUS_REPORT_MS,
  GAP_RESET_MS,
  IDLE_REPORT_MS,
  type AttentionSnapshot,
} from "./useAttentionSignals";

const T0 = 1_000_000;

function snap(overrides: Partial<AttentionSnapshot> = {}): AttentionSnapshot {
  return {
    now: T0,
    lastActivityAt: T0,
    spanStartAt: T0,
    runActive: false,
    idleReported: false,
    focusReported: false,
    ...overrides,
  };
}

describe("idle 上报", () => {
  it("无交互无回合 ≥30min → 上报一次（不重复）", () => {
    const idle = snap({ now: T0 + IDLE_REPORT_MS, lastActivityAt: T0 });
    const r1 = evaluateAttentionReport(idle);
    expect(r1.reports.map((x) => x.kind)).toEqual(["idle"]);
    expect(r1.reports[0].payload.idleMs).toBe(IDLE_REPORT_MS);
    const r2 = evaluateAttentionReport({ ...r1.next, now: T0 + IDLE_REPORT_MS + 60_000 });
    expect(r2.reports).toEqual([]);
  });

  it("run 进行中不算闲置（角色在工作）", () => {
    const r = evaluateAttentionReport(
      snap({ now: T0 + IDLE_REPORT_MS + 1, lastActivityAt: T0, runActive: true }),
    );
    expect(r.reports).toEqual([]);
  });

  it("差 1ms 不报（边界）", () => {
    const r = evaluateAttentionReport(snap({ now: T0 + IDLE_REPORT_MS - 1, lastActivityAt: T0 }));
    expect(r.reports).toEqual([]);
  });

  it("活动恢复后 idleReported 重置（可再次上报）", () => {
    const r1 = evaluateAttentionReport(snap({ now: T0 + IDLE_REPORT_MS, lastActivityAt: T0 }));
    expect(r1.next.idleReported).toBe(true);
    const active = evaluateAttentionReport({
      ...r1.next,
      now: T0 + IDLE_REPORT_MS + 1000,
      lastActivityAt: T0 + IDLE_REPORT_MS + 1000,
    });
    expect(active.next.idleReported).toBe(false);
  });
});

describe("focus_session 上报", () => {
  it("连续活跃 ≥55min → 上报一次", () => {
    // 连续活跃：span 起点 T0，用户一直有交互（lastActivityAt≈now）
    const r = evaluateAttentionReport(
      snap({ now: T0 + FOCUS_REPORT_MS, lastActivityAt: T0 + FOCUS_REPORT_MS }),
    );
    expect(r.reports.map((x) => x.kind)).toEqual(["focus_session"]);
    expect(r.reports[0].payload.activeMs).toBe(FOCUS_REPORT_MS);
    const again = evaluateAttentionReport({
      ...r.next,
      now: T0 + FOCUS_REPORT_MS + 60_000,
      lastActivityAt: T0 + FOCUS_REPORT_MS + 60_000,
    });
    expect(again.reports).toEqual([]);
  });

  it("活动断链 ≥5min → 跨度重算（断链期不计入）", () => {
    // 活跃到 T0+30min 后断链，T0+40min 巡检：跨度起点推到断链结束处
    const r = evaluateAttentionReport(
      snap({
        now: T0 + 30 * 60_000 + 10 * 60_000,
        lastActivityAt: T0 + 30 * 60_000,
      }),
    );
    expect(r.next.spanStartAt).toBe(T0 + 30 * 60_000 + 10 * 60_000 - GAP_RESET_MS);
    // 断链后需再连续 55min 才触发（用户已回来活跃，差 1ms 不报）
    const early = evaluateAttentionReport({
      ...r.next,
      now: r.next.spanStartAt + FOCUS_REPORT_MS - 1,
      lastActivityAt: r.next.spanStartAt + FOCUS_REPORT_MS - 61_000,
    });
    expect(early.reports).toEqual([]);
  });

  it("run 进行中活动不断链（跨度持续累积）", () => {
    const r = evaluateAttentionReport(
      snap({
        now: T0 + 40 * 60_000,
        lastActivityAt: T0, // 40min 无新交互
        runActive: true, // 但 run 一直在跑 → 不断链、不算闲置
      }),
    );
    expect(r.next.spanStartAt).toBe(T0); // 不重算
    // run 结束时用户刚有交互（54min 处回了句话）→ 跨度满 55min 触发
    const done = evaluateAttentionReport({
      ...r.next,
      now: T0 + FOCUS_REPORT_MS,
      runActive: false,
      lastActivityAt: T0 + FOCUS_REPORT_MS - 60_000,
    });
    expect(done.reports.map((x) => x.kind)).toEqual(["focus_session"]);
  });

  it("闲置期间跨度作废", () => {
    const r1 = evaluateAttentionReport(snap({ now: T0 + IDLE_REPORT_MS, lastActivityAt: T0 }));
    expect(r1.next.spanStartAt).toBe(T0 + IDLE_REPORT_MS); // 重置到当下
  });
});
