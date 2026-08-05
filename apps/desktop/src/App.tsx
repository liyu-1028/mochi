/**
 * M0-S3 布局 + M1-CTX 入口装配。
 *
 * 布局：
 * - 角色舞台（拖拽区）容纳 Live2D + 气泡区；左键唤起输入条、右键弹上下文菜单
 * - 底部 dock 槽位：状态文案与输入条共享同一位置、互斥显示
 * - 上下文菜单（CharacterMenu）→ 打开面板独立窗口（PanelShell，屏幕居中，
 *   不再以遮罩层挤在角色窗口内）
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { configApi } from "./api/configClient";
import { CharacterMenu, type MenuItemId } from "./components/CharacterMenu";
import { CharacterStage } from "./components/CharacterStage";
import { ChatToggle } from "./components/ChatToggle";
import { SpeechBubbleArea } from "./components/SpeechBubbleArea";
import { resolveWsUrl, useMochiConnection } from "./hooks/useMochiConnection";
import { useSettingsHydration } from "./hooks/useSettingsHydration";
import { useSidecarStatus } from "./hooks/useSidecarStatus";
import { useI18n } from "./i18n";
import { EVENT_ONBOARDING_DONE, EVENT_PROVIDERS_CHANGED, openPanelWindow } from "./panelWindow";
import { useConversation } from "./store/conversation";

export default function App() {
  const { sendText, cancelRun } = useMochiConnection(resolveWsUrl());
  const status = useConversation((s) => s.status);
  // release 下 sidecar 异常/重启的可读提示（1.2）；dev/浏览器为 null
  const sidecarHint = useSidecarStatus();
  const { t } = useI18n();
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  // 输入框开关上提到 App：点击角色唤起（CharacterStage.onActivate）
  const [chatOpen, setChatOpen] = useState(false);
  // 初始设置状态：null = 尚未探测；false = 明确未完成（状态栏提示）；true = 完成
  const [onboardingDone, setOnboardingDone] = useState<boolean | null>(null);
  // 会话内只自动弹一次引导窗：用户关掉后改用状态栏提示，不反复打扰
  const onboardingPrompted = useRef(false);

  // 语言设置事实源在 sidecar config；启动时同步，sidecar 未就绪则重试数次
  useSettingsHydration();

  // 面板窗口完成初始设置（一键 Ollama / 试用模式）后同步状态
  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    const unlisten = listen(EVENT_ONBOARDING_DONE, () => setOnboardingDone(true));
    return () => {
      unlisten.then((fn) => fn());
    };
  }, []);

  /**
   * 重新探测初始设置状态：有 provider → 完成；无 → 待设置（状态栏提示）。
   * 会话内首次探测到无 provider 时自动弹引导窗，之后只提示不再打扰。
   */
  const recheckOnboarding = useCallback(async () => {
    try {
      const providers = await configApi.listProviders();
      if (providers.length > 0) {
        setOnboardingDone(true);
      } else {
        setOnboardingDone(false);
        if (!onboardingPrompted.current) {
          onboardingPrompted.current = true;
          await openPanelWindow("onboarding");
        }
      }
    } catch {
      // sidecar 尚未就绪：等待下一次连接成功 / provider 变更再探测
    }
  }, []);

  // 连接成功后探测一次
  useEffect(() => {
    if (status !== "connected") return;
    void recheckOnboarding();
  }, [status, recheckOnboarding]);

  // 面板里增删 provider 后即时重查（删空 → 回到待设置提示）
  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    const unlisten = listen(EVENT_PROVIDERS_CHANGED, () => {
      void recheckOnboarding();
    });
    return () => {
      unlisten.then((fn) => fn());
    };
  }, [recheckOnboarding]);

  const handleMenuSelect = (item: MenuItemId) => {
    setMenu(null);
    void openPanelWindow(item);
  };

  return (
    <main className="app">
      {/* data-tauri-drag-region：Tauri 声明式窗口拖拽（功能清单 1.3）；
          浏览器环境下该属性无副作用。气泡区放在拖拽区外，避免点击气泡误触发拖动 */}
      <div className="app__stage" data-tauri-drag-region>
        <CharacterStage
          onActivate={() => setChatOpen(true)}
          onContextMenu={(x, y) => setMenu({ x, y })}
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
                ? onboardingDone === false
                  ? t("status.setupPending")
                  : t("status.connected")
                : status === "connecting"
                  ? t("status.connecting")
                  : t("status.disconnected"))}
          </footer>
        )}
      </div>

      {/* 右键上下文菜单（M1-CTX）：仍在光标处弹出，选中后打开面板独立窗口 */}
      {menu ? (
        <CharacterMenu
          x={menu.x}
          y={menu.y}
          onSelect={handleMenuSelect}
          onClose={() => setMenu(null)}
        />
      ) : null}
    </main>
  );
}
