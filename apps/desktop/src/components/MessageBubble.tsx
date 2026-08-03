import type { ChatMessage } from "../store/conversation";

export function MessageBubble({ message }: { message: ChatMessage }) {
  return (
    <div className={`bubble bubble--${message.role}`}>
      <div className="bubble__text">
        {message.text}
        {message.streaming ? <span className="bubble__cursor">▍</span> : null}
      </div>
    </div>
  );
}
