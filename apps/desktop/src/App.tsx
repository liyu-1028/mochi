/**
 * M0-S3 UI 重构：移除底部聊天面板，对话以浮动气泡呈现。
 *
 * 布局：
 * - 角色舞台（拖拽区）容纳 Live2D + 左侧气泡区
 * - 底部浮动聊天气泡按钮，点击展开紧凑输入框
 */
import { useState } from "react";
import { CharacterStage } from "./components/CharacterStage";
import { ChatToggle } from "./components/ChatToggle";
import { OnboardingWizard } from "./components/OnboardingWizard";
import { SettingsPanel } from "./components/SettingsPanel";
import { SpeechBubbleArea } from "./components/SpeechBubbleArea";
import { resolveWsUrl, useMochiConnection } from "./hooks/useMochiConnection";
import { useConversation } from "./store/conversation";
import "./styles/settings.css";

export default function App() {
  const { sendText, cancelRun } = useMochiConnection(resolveWsUrl());
  const status = useConversation((s) => s.status);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [onboardingDone, setOnboardingDone] = useState(false);

  return (
    <main className="app">
      <button
        className="app__settings-btn"
        onClick={() => setSettingsOpen(true)}
        title="模型设置"
        aria-label="模型设置"
      >
        ⚙
      </button>

      {/* data-tauri-drag-region：Tauri 声明式窗口拖拽（功能清单 1.3）；
          浏览器环境下该属性无副作用。气泡区放在拖拽区外，避免点击气泡误触发拖动 */}
      <div className="app__stage" data-tauri-drag-region>
        <CharacterStage />
      </div>
      <SpeechBubbleArea />

      <ChatToggle onSend={sendText} onCancel={cancelRun} />

      <footer className={`app__status app__status--${status}`}>
        {status === "connected" ? "已连接 sidecar" : status === "connecting" ? "连接中…" : "未连接"}
      </footer>

      {!onboardingDone ? (
        <OnboardingWizard
          onDone={() => setOnboardingDone(true)}
          onOpenSettings={() => setSettingsOpen(true)}
        />
      ) : null}
      {settingsOpen ? <SettingsPanel onClose={() => setSettingsOpen(false)} /> : null}
    </main>
  );
}
