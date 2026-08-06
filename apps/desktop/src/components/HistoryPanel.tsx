/**
 * HistoryPanel —— 聊天回忆面板（M1-CTX，功能清单 4.3 回看面）。
 *
 * 会话列表（最近活跃倒序）→ 点选回看消息（user/assistant 气泡，assistant
 * 走 MarkdownBody）→ 内联二次确认删除。只读回看，不切换实时上下文。
 * 复用 S1 的 sessionApi 与 settings.css 模态样式。
 */
import { useCallback, useEffect, useState } from "react";
import { sessionApi, type HistoryMessage, type SessionSummary } from "../api/configClient";
import { DEFAULT_SESSION_ID } from "../hooks/useMochiConnection";
import { useI18n } from "../i18n";
import { useConversation } from "../store/conversation";
import { MarkdownBody } from "./MarkdownBody";

interface HistoryPanelProps {
  onClose: () => void;
}

/** epoch 毫秒 → 本地化短日期（随界面语言）。 */
export function formatTs(ts: number, locale: string): string {
  const lang = locale === "en" ? "en-US" : "zh-CN";
  try {
    return new Intl.DateTimeFormat(lang, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(ts));
  } catch {
    return new Date(ts).toLocaleString();
  }
}

export function HistoryPanel({ onClose }: HistoryPanelProps) {
  const { t, locale } = useI18n();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<HistoryMessage[]>([]);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadSessions = useCallback(async () => {
    try {
      setSessions(await sessionApi.listSessions());
      setError(null);
    } catch {
      setError(t("settings.feedbackUnreachable"));
    }
  }, [t]);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  async function openSession(id: string) {
    setSelectedId(id);
    setConfirmDeleteId(null);
    try {
      setMessages(await sessionApi.getMessages(id));
    } catch {
      setMessages([]);
    }
  }

  async function handleDelete(id: string) {
    try {
      await sessionApi.deleteSession(id);
    } catch {
      // 删除失败不阻断：刷新列表即可看到真实状态
    }
    setConfirmDeleteId(null);
    if (selectedId === id) {
      setSelectedId(null);
      setMessages([]);
    }
    // 删除的是主界面活跃会话 → 同步清空内存消息，避免"后端已删、
    // 前端残留"的状态脱节（测试报告 2026-08-06 问题 2）
    if (id === DEFAULT_SESSION_ID) {
      useConversation.getState().resetMessages();
    }
    await loadSessions();
  }

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings" onClick={(e) => e.stopPropagation()}>
        {/* data-tauri-drag-region：无边框面板窗口以头部为拖拽区（button 子元素自动豁免） */}
        <header className="settings__header" data-tauri-drag-region>
          <h2>
            {selectedId ? (
              <button className="history__back" onClick={() => setSelectedId(null)}>
                ← {t("common.back")}
              </button>
            ) : null}
            {t("history.title")}
          </h2>
          <button className="settings__close" onClick={onClose} aria-label={t("common.close")}>
            ×
          </button>
        </header>

        {error ? <p className="settings__error">{error}</p> : null}

        {selectedId === null ? (
          sessions.length === 0 ? (
            <p className="settings__item-sub history__empty">{t("history.empty")}</p>
          ) : (
            <ul className="settings__list">
              {sessions.map((s) => (
                <li key={s.id} className="settings__item">
                  <button
                    type="button"
                    className="settings__item-main history__session"
                    onClick={() => openSession(s.id)}
                  >
                    <strong>{s.title ?? s.id}</strong>
                    <span className="settings__item-sub">{formatTs(s.updatedAt, locale)}</span>
                  </button>
                  <div className="settings__item-actions">
                    {confirmDeleteId === s.id ? (
                      <>
                        <button
                          className="btn btn--ghost settings__danger"
                          onClick={() => handleDelete(s.id)}
                        >
                          {t("common.delete")}
                        </button>
                        <button className="btn btn--ghost" onClick={() => setConfirmDeleteId(null)}>
                          {t("common.cancel")}
                        </button>
                      </>
                    ) : (
                      <button
                        className="btn btn--ghost settings__danger"
                        onClick={() => setConfirmDeleteId(s.id)}
                        aria-label={t("common.delete")}
                      >
                        🗑
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )
        ) : messages.length === 0 ? (
          <p className="settings__item-sub history__empty">{t("history.messagesEmpty")}</p>
        ) : (
          <div className="history__thread">
            {confirmDeleteId === selectedId ? (
              <div className="history__confirm">
                <span>{t("history.deleteConfirm")}</span>
                <button
                  className="btn btn--ghost settings__danger"
                  onClick={() => handleDelete(selectedId)}
                >
                  {t("common.delete")}
                </button>
                <button className="btn btn--ghost" onClick={() => setConfirmDeleteId(null)}>
                  {t("common.cancel")}
                </button>
              </div>
            ) : (
              <button
                className="btn btn--ghost settings__danger history__delete"
                onClick={() => setConfirmDeleteId(selectedId)}
              >
                {t("common.delete")}
              </button>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`history__msg history__msg--${m.role}`}>
                {m.role === "assistant" ? (
                  <MarkdownBody text={m.content} />
                ) : (
                  <span>{m.content}</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
