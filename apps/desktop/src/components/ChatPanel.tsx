import { useEffect, useRef } from "react";
import { useConversation } from "../store/conversation";
import { ChatInput } from "./ChatInput";
import { MessageBubble } from "./MessageBubble";

interface ChatPanelProps {
  onSend: (text: string) => void;
  onCancel: (runId: string) => void;
}

export function ChatPanel({ onSend, onCancel }: ChatPanelProps) {
  const messages = useConversation((s) => s.messages);
  const notice = useConversation((s) => s.notice);
  const clearNotice = useConversation((s) => s.clearNotice);
  const activeRunId = useConversation((s) => s.activeRunId);
  const listRef = useRef<HTMLDivElement>(null);

  // 新消息/流式增长时保持滚动到底部
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  return (
    <section className="chat">
      {notice ? (
        <div className="chat__notice" role="alert" onClick={clearNotice}>
          {notice}
        </div>
      ) : null}
      <div className="chat__messages" ref={listRef}>
        {messages.length === 0 ? (
          <p className="chat__empty">捏一捏我，开始聊天吧 ✨</p>
        ) : (
          messages.map((m) => <MessageBubble key={m.id} message={m} />)
        )}
      </div>
      <ChatInput onSend={onSend} onCancel={() => activeRunId && onCancel(activeRunId)} />
    </section>
  );
}
