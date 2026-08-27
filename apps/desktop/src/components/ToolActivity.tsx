/**
 * ToolActivity —— 工具调用的桌面呈现（M1-S4，功能清单 6.5/6.6）。
 *
 * 三块：
 * - ToolChips：working 期间贴气泡区上方的工具 chip 行——步骤序号 + 工具名
 *   + 运行计时（6.6 任务进度：执行中/等待确认实时跳秒，终态定格）；
 * - StopTask：working 期间的醒目停止按钮，回发 chat.cancel（4.2 语义）；
 * - ConfirmCard：pendingConfirm（requiresConfirmation 的 tool.call.start）到达时
 *   弹出的三键确认框——拒绝 / 允许 / 总是允许（后者 remember=true 入白名单，
 *   此后该工具不再询问）。回发走 tool.confirm 命令（协议 §4）。
 *
 * 终态兜底：run.finished/run.error 时 store 已把未收口 chip 置 error、清
 * pendingConfirm（finalizeToolCalls），确认框随之消失（cancel 场景）。
 */
import { useEffect, useState } from "react";
import { useI18n } from "../i18n";
import type { I18nVars } from "../i18n";
import { useConversation } from "../store/conversation";
import type { ToolCallView } from "../store/conversation";

/** 参数可读摘要：前 3 个键值对、单值截 40 字、总截 80 字（确认框展示用）。 */
export function summarizeArgs(args: Record<string, unknown>): string {
  const entries = Object.entries(args).slice(0, 3);
  const parts = entries.map(([k, v]) => {
    const value = typeof v === "string" ? v : JSON.stringify(v);
    const shown = value.length > 40 ? `${value.slice(0, 40)}…` : value;
    return `${k}=${shown}`;
  });
  if (Object.keys(args).length > 3) parts.push("…");
  const joined = parts.join("  ");
  return joined.length > 80 ? `${joined.slice(0, 80)}…` : joined;
}

/** 运行计时（6.6）：秒级展示，≥60s 转 m:ss；负值/NaN 兜底 0s。 */
export function formatElapsed(startedAt: number, now: number): string {
  const sec = Math.max(0, Math.floor((now - startedAt) / 1000));
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}

export function ToolActivity({
  confirmTool,
  onStop,
}: {
  confirmTool: (
    runId: string,
    toolCallId: string,
    decision: "allow" | "deny",
    remember?: boolean,
  ) => void;
  /** working 期间停止任务（chat.cancel，4.2：丢弃后续输出） */
  onStop: (runId: string) => void;
}) {
  const toolCalls = useConversation((s) => s.toolCalls);
  const pendingConfirm = useConversation((s) => s.pendingConfirm);
  const activeRunId = useConversation((s) => s.activeRunId);

  if (toolCalls.length === 0 && pendingConfirm === null) return null;
  const busy = toolCalls.some((c) => c.status === "running" || c.status === "confirming");

  return (
    <div className="tool-activity">
      {pendingConfirm !== null && activeRunId !== null ? (
        <ConfirmCard
          call={pendingConfirm}
          onDecide={(decision, remember) =>
            confirmTool(activeRunId, pendingConfirm.toolCallId, decision, remember)
          }
        />
      ) : null}
      {toolCalls.length > 0 ? <ToolChips calls={toolCalls} /> : null}
      {busy && activeRunId !== null ? <StopTask onStop={() => onStop(activeRunId)} /> : null}
    </div>
  );
}

/** 确认卡片：工具名 + 参数摘要 + 三键（拒绝 / 允许 / 总是允许）。 */
function ConfirmCard({
  call,
  onDecide,
}: {
  call: ToolCallView;
  onDecide: (decision: "allow" | "deny", remember?: boolean) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="confirm-card" role="alertdialog" aria-label={t("tools.confirmTitle")}>
      <div className="confirm-card__title">{t("tools.confirmTitle")}</div>
      <div className="confirm-card__tool">{call.name}</div>
      <div className="confirm-card__args">{summarizeArgs(call.args)}</div>
      <div className="confirm-card__actions">
        <button type="button" className="confirm-card__deny" onClick={() => onDecide("deny")}>
          {t("tools.confirmDeny")}
        </button>
        <button type="button" onClick={() => onDecide("allow")}>
          {t("tools.confirmAllow")}
        </button>
        <button type="button" onClick={() => onDecide("allow", true)}>
          {t("tools.confirmAlways")}
        </button>
      </div>
    </div>
  );
}

/** 工具 chip 行：步骤序号 + 图标 + 名称 +（进行中）运行计时。 */
function ToolChips({ calls }: { calls: ToolCallView[] }) {
  const { t } = useI18n();
  return (
    <div className="tool-chips">
      {calls.map((call, index) => (
        <ToolChip key={call.toolCallId} call={call} step={index + 1} t={t} />
      ))}
    </div>
  );
}

function ToolChip({
  call,
  step,
  t,
}: {
  call: ToolCallView;
  step: number;
  t: (key: string, vars?: I18nVars) => string;
}) {
  const live = call.status === "running" || call.status === "confirming";
  const [, forceTick] = useState(0);

  // 运行计时（6.6）：仅进行中的 chip 起秒表，终态不挂定时器（不空转）
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => forceTick((n) => n + 1), 1000);
    return () => window.clearInterval(timer);
  }, [live]);

  return (
    <span className={`tool-chip tool-chip--${call.status}`} title={statusTitle(call, t)}>
      <span className="tool-chip__step">{t("tools.step", { n: step })}</span>
      <span className="tool-chip__icon" aria-hidden>
        {ICON_BY_STATUS[call.status]}
      </span>
      <span className="tool-chip__name">{call.name}</span>
      {live ? (
        <span className="tool-chip__elapsed">{formatElapsed(call.startedAt, Date.now())}</span>
      ) : null}
    </span>
  );
}

/** 终态悬停文案：chip 定格后状态语义仍在（title 提示，不占横向空间）。 */
function statusTitle(call: ToolCallView, t: (key: string, vars?: I18nVars) => string): string {
  return t(LABEL_BY_STATUS[call.status], { name: call.name });
}

/** working 期间的停止按钮（6.6：可随时取消）。 */
function StopTask({ onStop }: { onStop: () => void }) {
  const { t } = useI18n();
  return (
    <button type="button" className="tool-stop" onClick={onStop}>
      ⏹ {t("tools.stopTask")}
    </button>
  );
}

const ICON_BY_STATUS: Record<ToolCallView["status"], string> = {
  confirming: "❓",
  running: "🔧",
  success: "✅",
  error: "⚠️",
  denied: "🚫",
};

const LABEL_BY_STATUS: Record<ToolCallView["status"], string> = {
  confirming: "tools.confirming",
  running: "tools.using",
  success: "tools.done",
  error: "tools.failed",
  denied: "tools.denied",
};
