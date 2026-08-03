/**
 * SpeechBubbleArea —— 角色旁边浮动对话气泡（M0-S3 UI 重构：移除底部聊天面板）。
 *
 * - 仅展示助手消息（用户消息已通过气泡旁的输入框发出，不重复展示）
 * - 同时最多 3 条：最新流式回复 + 最近 2 条已结束回复
 * - 左侧竖排，CSS 三角指向角色（右侧）
 * - 半透明黑底圆角，文本流式增长带 `▍` 光标
 * - pointer-events:none 让气泡不拦截窗口拖拽
 */
import { useEffect, useState } from "react";
import { useConversation } from "../store/conversation";
import type { ChatMessage } from "../store/conversation";

const MAX_BUBBLES = 3;

export function SpeechBubbleArea() {
  const messages = useConversation((s) => s.messages);
  // 仅显示助手消息，取最新 MAX_BUBBLES 条；流式回复始终置底以便看清
  const assistantMessages = messages.filter((m) => m.role === "assistant").slice(-MAX_BUBBLES);

  return (
    <div className="bubbles">
      {assistantMessages.map((m) => (
        <SpeechBubble key={m.id} message={m} />
      ))}
    </div>
  );
}

function SpeechBubble({ message }: { message: ChatMessage }) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    // 触发入场动画
    const t = setTimeout(() => setVisible(true), 0);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className={`bubble ${visible ? "bubble--enter" : ""}`}>
      <div className="bubble__body">
        {message.text || (message.streaming ? "…" : "")}
        {message.streaming && message.text ? <span className="bubble__cursor">▍</span> : null}
      </div>
      <span className="bubble__tail" aria-hidden />
    </div>
  );
}
