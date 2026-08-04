/**
 * M0-S3 UI 重构：移除底部聊天面板，对话以浮动气泡呈现。
 *
 * 布局：
 * - 角色舞台（拖拽区）容纳 Live2D + 左侧气泡区
 * - 底部 dock 槽位：状态文案与输入条共享同一位置、互斥显示
 *   （展开输入条时不渲染文案；dock 参与流式布局，输入条不遮挡角色）
 */
import { useState } from "react";
import { CharacterStage } from "./components/CharacterStage";
import { ChatToggle } from "./components/ChatToggle";
import { OnboardingWizard } from "./components/OnboardingWizard";
import { SettingsPanel } from "./components/SettingsPanel";
import { SpeechBubbleArea } from "./components/SpeechBubbleArea";
import { resolveWsUrl, useMochiConnection } from "./hooks/useMochiConnection";
import { useSidecarStatus } from "./hooks/useSidecarStatus";
import { useConversation } from "./store/conversation";
import "./styles/settings.css";

export default function App() {
  const { sendText, cancelRun } = useMochiConnection(resolveWsUrl());
  const status = useConversation((s) => s.status);
  // release 下 sidecar 异常/重启的可读提示（1.2）；dev/浏览器为 null
  const sidecarHint = useSidecarStatus();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [onboardingDone, setOnboardingDone] = useState(false);
  // 输入框开关上提到 App：点击角色唤起（CharacterStage.onActivate）
  const [chatOpen, setChatOpen] = useState(false);

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
        <CharacterStage onActivate={() => setChatOpen(true)} />
      </div>
      <SpeechBubbleArea />

      {/* 底部 dock 槽位：状态文案与输入条共享同一位置、互斥显示——
          条件渲染保证两者不会同时出现；dock 在流式布局中固定高度，
          角色舞台止于其上，输入条永不遮挡 Mochi 形象 */}
      <div className="app__dock">
        {chatOpen ? (
          <ChatToggle
            open={chatOpen}
            onOpenChange={setChatOpen}
            onSend={sendText}
            onCancel={cancelRun}
          />
        ) : (
          <footer
            className={`app__status ${sidecarHint ? "app__status--error" : `app__status--${status}`}`}
          >
            {sidecarHint ??
              (status === "connected"
                ? "已连接 · 点击 Mochi 聊天"
                : status === "connecting"
                  ? "连接中…"
                  : "未连接")}
          </footer>
        )}
      </div>

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
