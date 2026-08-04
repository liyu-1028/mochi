/**
 * M0-S3 布局 + M1-CTX 入口装配。
 *
 * 布局：
 * - 角色舞台（拖拽区）容纳 Live2D + 气泡区；左键唤起输入条、右键弹上下文菜单
 * - 底部 dock 槽位：状态文案与输入条共享同一位置、互斥显示
 * - 上下文菜单（CharacterMenu）→ 三个功能面板互斥打开（activePanel 单一状态）
 */
import { useEffect, useState } from "react";
import { CharacterMenu, type MenuItemId } from "./components/CharacterMenu";
import { CharacterStage } from "./components/CharacterStage";
import { ChatToggle } from "./components/ChatToggle";
import { HistoryPanel } from "./components/HistoryPanel";
import { OnboardingWizard } from "./components/OnboardingWizard";
import { SettingsPanel } from "./components/SettingsPanel";
import { SkinsPanel } from "./components/SkinsPanel";
import { SpeechBubbleArea } from "./components/SpeechBubbleArea";
import { resolveWsUrl, useMochiConnection } from "./hooks/useMochiConnection";
import { useSidecarStatus } from "./hooks/useSidecarStatus";
import { useI18n } from "./i18n";
import { useConversation } from "./store/conversation";
import { useSettings } from "./store/settings";
import "./styles/settings.css";

/** 三个功能面板（同一时刻最多打开一个）。 */
type PanelId = "settings" | "history" | "skins";

export default function App() {
  const { sendText, cancelRun } = useMochiConnection(resolveWsUrl());
  const status = useConversation((s) => s.status);
  // release 下 sidecar 异常/重启的可读提示（1.2）；dev/浏览器为 null
  const sidecarHint = useSidecarStatus();
  const { t } = useI18n();
  const [activePanel, setActivePanel] = useState<PanelId | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const [onboardingDone, setOnboardingDone] = useState(false);
  // 输入框开关上提到 App：点击角色唤起（CharacterStage.onActivate）
  const [chatOpen, setChatOpen] = useState(false);

  // 语言设置事实源在 sidecar config；启动时同步，sidecar 未就绪则重试数次
  useEffect(() => {
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tryHydrate = async () => {
      attempts += 1;
      const ok = await useSettings.getState().hydrate();
      if (!ok && attempts < 5) {
        timer = setTimeout(tryHydrate, 1500);
      }
    };
    void tryHydrate();
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, []);

  // 打开面板即关菜单；菜单与面板互斥
  const openPanel = (id: PanelId) => {
    setMenu(null);
    setActivePanel(id);
  };
  const handleMenuSelect = (item: MenuItemId) => openPanel(item);

  return (
    <main className="app">
      {/* data-tauri-drag-region：Tauri 声明式窗口拖拽（功能清单 1.3）；
          浏览器环境下该属性无副作用。气泡区放在拖拽区外，避免点击气泡误触发拖动 */}
      <div className="app__stage" data-tauri-drag-region>
        <CharacterStage
          onActivate={() => setChatOpen(true)}
          onContextMenu={(x, y) => {
            if (activePanel === null) setMenu({ x, y });
          }}
        />
      </div>
      <SpeechBubbleArea />

      {/* 底部 dock 槽位：状态文案与输入条共享同一位置、互斥显示 */}
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
                ? t("status.connected")
                : status === "connecting"
                  ? t("status.connecting")
                  : t("status.disconnected"))}
          </footer>
        )}
      </div>

      {/* 右键上下文菜单（M1-CTX） */}
      {menu ? (
        <CharacterMenu
          x={menu.x}
          y={menu.y}
          onSelect={handleMenuSelect}
          onClose={() => setMenu(null)}
        />
      ) : null}

      {!onboardingDone ? (
        <OnboardingWizard
          onDone={() => setOnboardingDone(true)}
          onOpenSettings={() => openPanel("settings")}
        />
      ) : null}

      {activePanel === "settings" ? <SettingsPanel onClose={() => setActivePanel(null)} /> : null}
      {activePanel === "history" ? <HistoryPanel onClose={() => setActivePanel(null)} /> : null}
      {activePanel === "skins" ? <SkinsPanel onClose={() => setActivePanel(null)} /> : null}
    </main>
  );
}
