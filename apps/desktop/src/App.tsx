import { CharacterBadge } from "./components/CharacterBadge";
import { ChatPanel } from "./components/ChatPanel";
import { resolveWsUrl, useMochiConnection } from "./hooks/useMochiConnection";
import { useConversation } from "./store/conversation";

/**
 * M0-S1：端到端流式对话垂直切片。
 * 上半区为角色占位表现（S3 替换为 Live2D），下半区为对话面板。
 */
export default function App() {
  const { sendText, cancelRun } = useMochiConnection(resolveWsUrl());
  const status = useConversation((s) => s.status);

  return (
    <main className="app">
      <div className="app__stage">
        <CharacterBadge />
      </div>
      <ChatPanel onSend={sendText} onCancel={cancelRun} />
      <footer className={`app__status app__status--${status}`}>
        {status === "connected" ? "已连接 sidecar" : status === "connecting" ? "连接中…" : "未连接"}
      </footer>
    </main>
  );
}
