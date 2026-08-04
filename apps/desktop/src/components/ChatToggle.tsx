/**
 * ChatToggle —— 底部浮动输入条。
 *
 * - 唤起方式：点击 Mochi 角色（CharacterStage.onActivate，open 由 App 持有）
 * - 展开态：半透明输入条（输入 + 发送/停止）
 * - 关闭路径统一：Esc / 点击外部 / × 按钮 / idle 超时，全部走 handleClose
 *   先播 panel-pop-out 反向动画（180ms），再通知 App 卸载面板
 * - 自动隐藏：打开后 5s 未悬停/无草稿/无活跃回合，自动收起
 *   （暂停信号聚合由 shouldKeepPanelOpen 承担，详见 useIdlePanelTimer）
 * - 输入框不进入窗口拖拽区（独立于 .app__stage）
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useConversation } from "../store/conversation";
import {
  IDLE_TIMEOUT_MS,
  shouldKeepPanelOpen,
  useIdlePanelTimer,
} from "../hooks/useIdlePanelTimer";

interface ChatToggleProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSend: (text: string) => void;
  onCancel: (runId: string) => void;
}

/** 关闭动画时长，与 styles.css panel-pop-out 一致 */
const CLOSE_ANIM_MS = 180;

export function ChatToggle({ open, onOpenChange, onSend, onCancel }: ChatToggleProps) {
  const [text, setText] = useState("");
  const [hovered, setHovered] = useState(false);
  const [closing, setClosing] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  // 关闭动画定时器引用：用于卸载 / 重新打开时取消挂起的 onOpenChange
  const closeTimerRef = useRef<number | null>(null);
  const status = useConversation((s) => s.status);
  const activeRunId = useConversation((s) => s.activeRunId);
  const isStreaming = activeRunId !== null;

  // 展开时聚焦输入框
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // 重新打开时清掉 closing 与未完成的关闭动画定时器（避免重新打开后又被旧定时器关闭）
  useEffect(() => {
    if (!open) return;
    setClosing(false);
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  }, [open]);

  // 卸载兜底：避免 setTimeout 在已卸载组件上回调
  useEffect(() => {
    return () => {
      if (closeTimerRef.current !== null) {
        window.clearTimeout(closeTimerRef.current);
        closeTimerRef.current = null;
      }
    };
  }, []);

  // 统一关闭：先播 panel-pop-out 反向动画，CLOSE_ANIM_MS 后再通知 App
  // 防重入：closing 已为 true 时直接忽略（idle/Esc/外部/× 可能同时触发）
  const handleClose = useCallback(() => {
    if (closing) return;
    setClosing(true);
    closeTimerRef.current = window.setTimeout(() => {
      closeTimerRef.current = null;
      onOpenChange(false);
    }, CLOSE_ANIM_MS);
  }, [closing, onOpenChange]);

  // idle 自动隐藏：未悬停/无草稿/无活跃回合时计时，超时触发 handleClose
  // 故意不把 input 焦点当暂停信号——打开后输入框自动聚焦，焦点会一直挂着，
  // 若纳入暂停条件会导致计时器永远跑不起来（参见 useIdlePanelTimer 注释）
  const paused =
    !open ||
    closing ||
    shouldKeepPanelOpen({
      isHovered: hovered,
      hasPendingInput: text.length > 0,
      hasActiveRun: isStreaming,
    });
  useIdlePanelTimer({ paused, onIdle: handleClose, timeoutMs: IDLE_TIMEOUT_MS });

  // Esc 收起
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        handleClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, handleClose]);

  // 点击外部收起
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const node = containerRef.current;
      if (node && !node.contains(e.target as Node)) {
        handleClose();
      }
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open, handleClose]);

  const submit = () => {
    const value = text.trim();
    if (!value || isStreaming) return;
    onSend(value);
    setText("");
    // 发送后保持展开（用户可连续对话），idle 计时器由 hasPendingInput / hasActiveRun 暂停
  };

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className={`chat-toggle${open ? " chat-toggle--open" : ""}`} ref={containerRef}>
      {open ? (
        <div
          className={`chat-toggle__panel${closing ? " chat-toggle__panel--closing" : ""}`}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
        >
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
            onClick={handleClose}
            title="收起（Esc）"
            aria-label="收起"
          >
            ×
          </button>
        </div>
      ) : null}
    </div>
  );
}
