import { useState, type FormEvent } from "react";
import { useConversation } from "../store/conversation";

interface ChatInputProps {
  onSend: (text: string) => void;
  onCancel: () => void;
}

export function ChatInput({ onSend, onCancel }: ChatInputProps) {
  const [text, setText] = useState("");
  const status = useConversation((s) => s.status);
  const activeRunId = useConversation((s) => s.activeRunId);

  const connected = status === "connected";
  const running = activeRunId !== null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!connected || running || !text.trim()) return;
    onSend(text);
    setText("");
  };

  return (
    <form className="chat__input" onSubmit={submit}>
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={connected ? "和 Mochi 说点什么…" : "连接中…"}
        disabled={!connected}
        aria-label="对话输入框"
      />
      {running ? (
        <button type="button" className="btn btn--ghost" onClick={onCancel}>
          停止
        </button>
      ) : (
        <button type="submit" className="btn" disabled={!connected || !text.trim()}>
          发送
        </button>
      )}
    </form>
  );
}
