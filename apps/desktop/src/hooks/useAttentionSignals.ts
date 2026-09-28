/**
 * useAttentionSignals —— 环境陪伴信号上报（M-D D3，调研报告 §8.2）。
 *
 * 前端只报告「事实」，是否开口由服务端注意力引擎门控（§8.6）：
 * - idle：无交互且无回合持续 ≥ IDLE_REPORT_MS → 上报一次（引擎 silent 记账，
 *   M-E 上下文感知的铺垫）；
 * - focus_session：连续活跃跨度（活动间隔 < GAP_RESET_MS 不断链）≥
 *   FOCUS_REPORT_MS → 上报一次（引擎判定 ≥50min 触发休息提醒 ask）。
 *
 * 「活跃」的边界（v1 如实记录）：仅本应用窗口内的指针/键盘事件与进行中
 * 的回合——系统级空闲检测需要 OS 权限，属 M-E 范围。
 * 纯逻辑抽为 evaluateAttentionReport 便于单测（无定时器依赖）。
 */
import { type SignalKind, type SignalSalience } from "@mochi/protocol";
import { useEffect, useRef } from "react";
import { useConversation } from "../store/conversation";

/** 闲置上报阈值：30 分钟无交互无回合 */
export const IDLE_REPORT_MS = 30 * 60 * 1000;
/** 连续活跃上报阈值：55 分钟（引擎侧阈值 50min，留提前量） */
export const FOCUS_REPORT_MS = 55 * 60 * 1000;
/** 活动断链间隔：超过 5 分钟无活动 → 连续活跃跨度重新起算 */
export const GAP_RESET_MS = 5 * 60 * 1000;
/** 巡检间隔 */
const TICK_MS = 60 * 1000;

export type SendSignal = (
  kind: SignalKind,
  salience: SignalSalience,
  payload: Record<string, unknown>,
) => void;

/** 巡检快照（可测纯函数的输入） */
export interface AttentionSnapshot {
  now: number;
  lastActivityAt: number;
  spanStartAt: number;
  /** 进行中的回合（activeRunId 非空时活动视为持续不断链） */
  runActive: boolean;
  idleReported: boolean;
  focusReported: boolean;
}

export interface AttentionReport {
  kind: SignalKind;
  salience: SignalSalience;
  payload: Record<string, unknown>;
}

/** 纯函数：由快照判定应上报的信号与派生的新快照（无副作用，vitest 直测）。 */
export function evaluateAttentionReport(snap: AttentionSnapshot): {
  reports: AttentionReport[];
  next: AttentionSnapshot;
} {
  const next: AttentionSnapshot = { ...snap };
  const reports: AttentionReport[] = [];
  const idleMs = snap.now - snap.lastActivityAt;

  // 闲置判定：无回合 + 无交互超阈值。run 进行中不算闲置（角色在工作）
  if (!snap.runActive && idleMs >= IDLE_REPORT_MS) {
    if (!snap.idleReported) {
      reports.push({ kind: "idle", salience: 0, payload: { idleMs } });
      next.idleReported = true;
    }
    // 闲置期间连续活跃跨度作废、下次活动重新起算
    next.spanStartAt = snap.now;
    next.focusReported = false;
    return { reports, next };
  }

  // 活动恢复：闲置上报标志重置（下次再闲置可再报）
  next.idleReported = false;

  // 活动断链（无交互超 GAP 且无回合兜底）→ 跨度起点推到最近一次「链断」处
  const gap = snap.now - snap.lastActivityAt;
  if (!snap.runActive && gap >= GAP_RESET_MS) {
    // 断链期不计入活跃跨度：起点 = 断链结束处（即最近活动时刻附近的链界）
    next.spanStartAt = Math.max(next.spanStartAt, snap.now - GAP_RESET_MS);
  }

  const spanMs = snap.now - next.spanStartAt;
  if (!snap.focusReported && spanMs >= FOCUS_REPORT_MS) {
    reports.push({ kind: "focus_session", salience: 1, payload: { activeMs: spanMs } });
    next.focusReported = true;
  }
  return { reports, next };
}

export function useAttentionSignals(send: SendSignal): void {
  const snapRef = useRef<AttentionSnapshot>({
    now: Date.now(),
    lastActivityAt: Date.now(),
    spanStartAt: Date.now(),
    runActive: false,
    idleReported: false,
    focusReported: false,
  });
  const sendRef = useRef(send);
  sendRef.current = send;

  useEffect(() => {
    const bump = () => {
      snapRef.current.lastActivityAt = Date.now();
    };
    const events: Array<keyof WindowEventMap> = ["pointerdown", "keydown", "pointermove"];
    events.forEach((e) => window.addEventListener(e, bump, { passive: true }));

    // 回合状态订阅：run 进行中活动视为持续（不断链、不算闲置）
    const unsubscribe = useConversation.subscribe((s) => {
      snapRef.current.runActive = s.activeRunId !== null;
    });

    const timer = setInterval(() => {
      snapRef.current.now = Date.now();
      const { reports, next } = evaluateAttentionReport(snapRef.current);
      snapRef.current = next;
      for (const r of reports) sendRef.current(r.kind, r.salience, r.payload);
    }, TICK_MS);

    return () => {
      events.forEach((e) => window.removeEventListener(e, bump));
      clearInterval(timer);
      unsubscribe();
    };
  }, []);
}
