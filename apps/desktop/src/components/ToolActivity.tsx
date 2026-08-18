/**
 * ToolActivity —— 工具调用的桌面呈现（M1-S4，功能清单 6.5/6.6）。
 *
 * 两块：
 * - ToolChips：working 期间贴气泡区上方的工具 chip 行（执行中/成功/失败/被拒），
 *   数据源 conversation.toolCalls（run 开始清空）；
 * - ConfirmCard：pendingConfirm（requiresConfirmation 的 tool.call.start）到达时
 *   弹出的三键确认框——拒绝 / 允许 / 总是允许（后者 remember=true 入白名单，
 *   此后该工具不再询问）。回发走 tool.confirm 命令（协议 §4）。
 *
 * 终态兜底：run.finished/run.error 时 store 已把未收口 chip 置 error、清
 * pendingConfirm（finalizeToolCalls），确认框随之消失（cancel 场景）。
 */
import { useI18n } from "../i18n";
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

export function ToolActivity({
  confirmTool,
}: {
  confirmTool: (
    runId: string,
    toolCallId: string,
    decision: "allow" | "deny",
    remember?: boolean,
  ) => void;
}) {
  const toolCalls = useConversation((s) => s.toolCalls);
  const pendingConfirm = useConversation((s) => s.pendingConfirm);
  const activeRunId = useConversation((s) => s.activeRunId);

  if (toolCalls.length === 0 && pendingConfirm === null) return null;

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

/** 工具 chip 行：图标 + 名称 + 状态文案。 */
function ToolChips({ calls }: { calls: ToolCallView[] }) {
  const { t } = useI18n();
  return (
    <div className="tool-chips">
      {calls.map((call) => (
        <span key={call.toolCallId} className={`tool-chip tool-chip--${call.status}`}>
          <span className="tool-chip__icon" aria-hidden>
            {ICON_BY_STATUS[call.status]}
          </span>
          {t(LABEL_BY_STATUS[call.status], { name: call.name })}
        </span>
      ))}
    </div>
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
