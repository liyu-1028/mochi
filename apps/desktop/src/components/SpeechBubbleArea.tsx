/**
 * SpeechBubbleArea —— 角色旁边浮动对话气泡（M0-S3 UI 重构）。
 *
 * 渐进淡出 + 悬停激活方案：
 * - 气泡不消失，按"距最新消息"的层数逐渐变淡变小（最近的最显眼）
 * - 鼠标移上 bubbles 区域，全部气泡全亮 + 正常大小，方便回看
 * - 不依赖定时器，没有"错过时机丢历史"的尴尬
 * - pointer-events:none 让气泡不拦截窗口拖拽
 */
import { useEffect, useState } from "react";
import { useConversation } from "../store/conversation";
import type { ChatMessage } from "../store/conversation";

const MAX_AGE = 3; // 0 = 最新, 1 = 上一个, 2 = 再上一个, 3+ = 上限样式

export function SpeechBubbleArea() {
  const messages = useConversation((s) => s.messages);
  const assistantMessages = messages.filter((m) => m.role === "assistant");

  return (
    <div className="bubbles">
      {assistantMessages.map((m, i) => {
        const ageFromNewest = assistantMessages.length - 1 - i;
        return <SpeechBubble key={m.id} message={m} age={ageFromNewest} />;
      })}
    </div>
  );
}

function SpeechBubble({ message, age }: { message: ChatMessage; age: number }) {
  // 入场动画：初始 opacity:0 偏移 → entered 触发后过渡到 age 样式
  const [entered, setEntered] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setEntered(true), 0);
    return () => clearTimeout(t);
  }, []);

  const ageClass = age === 0 ? "" : `bubble--age-${Math.min(age, MAX_AGE)}`;
  return (
    <div className={`bubble ${ageClass} ${entered ? "bubble--entered" : ""}`}>
      <div className="bubble__body">
        {message.text || (message.streaming ? "…" : "")}
        {message.streaming && message.text ? <span className="bubble__cursor">▍</span> : null}
      </div>
      <span className="bubble__tail" aria-hidden />
    </div>
  );
}
