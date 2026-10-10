/**
 * HistoryPanel —— 聊天回忆面板（M1-CTX，功能清单 4.3 回看面）。
 *
 * 会话列表（最近活跃倒序）→ 点选回看消息（user/assistant 气泡，assistant
 * 走 MarkdownBody）→ 继续旧会话 / 新建会话 / 内联二次确认删除。
 * 复用 S1 的 sessionApi 与 settings.css 模态样式。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { emit } from "@tauri-apps/api/event";
import { sessionApi, type HistoryMessage, type SessionSummary } from "../api/configClient";
import { useI18n } from "../i18n";
import { EVENT_SESSION_CHANGED } from "../panelWindow";
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
  const activeSessionId = useConversation((s) => s.activeSessionId);
  const messageRequest = useRef(0);
  const visibleSessions = sessions.some((s) => s.id === activeSessionId)
    ? sessions
    : [
        { id: activeSessionId, title: t("history.newTitle"), createdAt: 0, updatedAt: 0 },
        ...sessions,
      ];

  async function activateSession(id: string) {
    try {
      if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
        await emit(EVENT_SESSION_CHANGED, { sessionId: id });
      }
      useConversation.getState().activateSession(id);
      onClose();
    } catch {
      setError(t("settings.feedbackUnreachable"));
    }
  }

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
    setError(null);
    const request = ++messageRequest.current;
    setSelectedId(id);
    setConfirmDeleteId(null);
    setMessages([]);
    try {
      const history = await sessionApi.getMessages(id);
      if (request === messageRequest.current) setMessages(history);
    } catch {
      if (request === messageRequest.current) setError(t("settings.feedbackUnreachable"));
    }
  }

  async function handleDelete(id: string) {
    try {
      await sessionApi.deleteSession(id);
    } catch {
      setError(t("settings.feedbackUnreachable"));
      return;
    }
    setConfirmDeleteId(null);
    if (selectedId === id) {
      setSelectedId(null);
      setMessages([]);
    }
    // 删除当前会话后进入新的空白会话，其他会话及长期记忆保持独立。
    if (id === activeSessionId) await activateSession(crypto.randomUUID());
    await loadSessions();
  }

  return (
    <div className="settings-overlay settings-overlay--history" onClick={onClose}>
      <div className="settings settings--history" onClick={(e) => e.stopPropagation()}>
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

        <div className="history__toolbar">
          <p className="settings__item-sub">{t("history.sessionHint")}</p>
          <button className="btn" onClick={() => void activateSession(crypto.randomUUID())}>
            {t("history.newSession")}
          </button>
        </div>
        <details className="history__guide">
          <summary>{t("history.whenToStart")}</summary>
          <p className="settings__item-sub">{t("history.sessionGuide")}</p>
        </details>

        {selectedId ? (
          <div className="history__toolbar">
            <span className="settings__item-sub">
              {t("history.messageCount", { count: messages.length })}
            </span>
            <button className="btn btn--ghost" onClick={() => void activateSession(selectedId)}>
              {t("history.continue")}
            </button>
          </div>
        ) : null}
        {selectedId && messages.length > 20 ? (
          <p className="settings__item-sub">{t("history.longSession")}</p>
        ) : null}

        {error ? <p className="settings__error">{error}</p> : null}

        {selectedId === null ? (
          <ul className="settings__list">
            {visibleSessions.map((s) => (
              <li key={s.id} className="settings__item">
                <button
                  type="button"
                  className="settings__item-main history__session"
                  onClick={() => openSession(s.id)}
                >
                  <strong>{s.title ?? t("history.newTitle")}</strong>
                  <span className="settings__item-sub">
                    {s.updatedAt ? formatTs(s.updatedAt, locale) : t("history.notStarted")}
                  </span>
                </button>
                <div className="settings__item-actions">
                  {s.id === activeSessionId ? (
                    <span className="settings__tag">{t("history.current")}</span>
                  ) : null}
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
                  ) : s.updatedAt ? (
                    <button
                      className="btn btn--ghost settings__danger"
                      onClick={() => setConfirmDeleteId(s.id)}
                      aria-label={t("common.delete")}
                    >
                      🗑
                    </button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
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
