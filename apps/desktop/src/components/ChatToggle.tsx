/**
 * ChatToggle —— 底部浮动聊天气泡按钮，点击展开简洁输入框（M0-S3 UI 重构）。
 *
 * - 收起态：右下角 💬 圆按钮
 * - 展开态：紧凑输入框（输入 + 发送/停止），Esc 或点击外部收起
 * - 输入框不进入窗口拖拽区（独立于 .app__stage）
 */
import { useEffect, useRef, useState } from "react";
import { useConversation } from "../store/conversation";

interface ChatToggleProps {
  onSend: (text: string) => void;
  onCancel: (runId: string) => void;
}

export function ChatToggle({ onSend, onCancel }: ChatToggleProps) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const status = useConversation((s) => s.status);
  const activeRunId = useConversation((s) => s.activeRunId);
  const isStreaming = activeRunId !== null;

  // 展开时聚焦输入框
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Esc 收起
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // 点击外部收起
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const node = containerRef.current;
      if (node && !node.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  const submit = () => {
    const value = text.trim();
    if (!value || isStreaming) return;
    onSend(value);
    setText("");
    // 发送后保持展开，便于连续对话；用户可手动收起
  };

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="chat-toggle" ref={containerRef}>
      {open ? (
        <div className="chat-toggle__panel">
          <input
            ref={inputRef}
            type="text"
            className="chat-toggle__input"
            placeholder={status === "connected" ? "和 Mochi 说点什么…" : "连接中…"}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKey}
            disabled={status !== "connected"}
          />
          {isStreaming ? (
            <button
              className="chat-toggle__btn chat-toggle__btn--stop"
              type="button"
              onClick={() => activeRunId && onCancel(activeRunId)}
              title="停止生成"
              aria-label="停止生成"
            >
              ⏹
            </button>
          ) : (
            <button
              className="chat-toggle__btn chat-toggle__btn--send"
              type="button"
              onClick={submit}
              disabled={text.trim().length === 0 || status !== "connected"}
              title="发送（Enter）"
              aria-label="发送"
            >
              ➤
            </button>
          )}
          <button
            className="chat-toggle__close"
            type="button"
            onClick={() => setOpen(false)}
            title="收起（Esc）"
            aria-label="收起"
          >
            ×
          </button>
        </div>
      ) : (
        <button
          className="chat-toggle__trigger"
          type="button"
          onClick={() => setOpen(true)}
          title="和 Mochi 聊天"
          aria-label="和 Mochi 聊天"
        >
          💬
        </button>
      )}
    </div>
  );
}
