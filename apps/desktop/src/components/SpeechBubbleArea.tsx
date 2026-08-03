/**
 * SpeechBubbleArea —— 角色旁边浮动对话气泡（M0-S3 UI 重构）。
 *
 * 自动隐藏 + 悬停保持方案：
 * - 每条气泡按消息字符数计算"阅读延迟"（base + 150ms/字），超时自动隐藏
 * - 鼠标悬停在气泡区时：所有气泡显示，定时器暂停
 * - 鼠标离开后：定时器重新启动，继续按延迟隐藏
 * - 流式 delta 时延迟随字符数增长（用户边看边接收新内容）
 *
 * 提示：容器放在 .app__stage 之外，避免气泡点击误触发 Tauri 窗口拖动。
 */
import { useEffect, useRef, useState } from "react";
import { useConversation } from "../store/conversation";
import type { ChatMessage } from "../store/conversation";

/** 阅读延迟估算（中文 ~5–7 字/秒 + 起始缓冲 + 上限封顶） */
function computeHideDelay(text: string): number {
  const base = 2000;
  const perChar = 150;
  const max = 15000;
  return Math.min(base + text.length * perChar, max);
}

export function SpeechBubbleArea() {
  const messages = useConversation((s) => s.messages);
  const assistantMessages = messages.filter((m) => m.role === "assistant");
  const [hover, setHover] = useState(false);

  return (
    <div
      className="bubbles"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      {assistantMessages.map((m) => (
        <SpeechBubble key={m.id} message={m} hovered={hover} />
      ))}
    </div>
  );
}

function SpeechBubble({ message, hovered }: { message: ChatMessage; hovered: boolean }) {
  const [hidden, setHidden] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // 依赖 hover 与文本：hover 状态切换或文本增长都重置定时器
    if (timerRef.current) clearTimeout(timerRef.current);
    if (hovered) {
      // 悬停期间显示且暂停定时器
      setHidden(false);
      return;
    }
    timerRef.current = setTimeout(() => {
      setHidden(true);
    }, computeHideDelay(message.text));
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [message.text, hovered]);

  return (
    <div className={`bubble ${hidden ? "bubble--hidden" : ""}`}>
      <div className="bubble__body">
        {message.text || (message.streaming ? "…" : "")}
        {message.streaming && message.text ? <span className="bubble__cursor">▍</span> : null}
      </div>
      <span className="bubble__tail" aria-hidden />
    </div>
  );
}
