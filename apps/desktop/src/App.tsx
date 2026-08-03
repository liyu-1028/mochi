import { useState } from "react";
import { CharacterStage } from "./components/CharacterStage";
import { ChatPanel } from "./components/ChatPanel";
import { OnboardingWizard } from "./components/OnboardingWizard";
import { SettingsPanel } from "./components/SettingsPanel";
import { resolveWsUrl, useMochiConnection } from "./hooks/useMochiConnection";
import { useConversation } from "./store/conversation";
import "./styles/settings.css";

/**
 * M0-S3：Live2D 角色渲染。
 * 上半区为 CharacterStage（Live2D，失败降级 emoji 占位），下半区为对话面板；
 * 右上齿轮进入模型设置；首次运行无 provider 时展示引导向导。
 */
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
          浏览器环境下该属性无副作用 */}
      <div className="app__stage" data-tauri-drag-region>
        <CharacterStage />
      </div>
      <ChatPanel onSend={sendText} onCancel={cancelRun} />
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
