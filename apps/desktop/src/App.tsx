/**
 * M0-S3 布局 + M1-CTX 入口装配。
 *
 * 布局：
 * - 窗口尺寸动态贴合角色（布局倒置）：模型加载完成回传原始尺寸 →
 *   computeCharacterLayout 推导窗口尺寸 → applyCharacterLayout 同步 OS 窗口；
 *   气泡渲染在角色图层之上、头部侧向贴近（useBubbleSide 按屏幕位置选边），
 *   出现/消失不改变窗口尺寸
 * - 角色舞台（拖拽区）容纳 Live2D；左键唤起输入条、右键弹上下文菜单
 * - 底部 dock 槽位：状态文案与输入条共享同一位置、互斥显示
 * - 上下文菜单（CharacterMenu）→ 打开面板独立窗口（PanelShell，屏幕居中，
 *   不再以遮罩层挤在角色窗口内）
 * - 浏览器环境（dev:web 等无 Tauri runtime）无法建独立窗口，面板与
 *   引导向导降级为窗口内内联模态（IS_TAURI 分支）；OS resize 同样 no-op
 */
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { listen } from "@tauri-apps/api/event";
import { configApi } from "./api/configClient";
import { initRuntimePortListener, subscribeRuntimePort } from "./api/sidecarRuntime";
import { CharacterMenu, type MenuItemId } from "./components/CharacterMenu";
import { CharacterStage } from "./components/CharacterStage";
import { ChatToggle } from "./components/ChatToggle";
import { HistoryPanel } from "./components/HistoryPanel";
import { OnboardingWizard } from "./components/OnboardingWizard";
import { SettingsPanel } from "./components/SettingsPanel";
import { SkinsPanel } from "./components/SkinsPanel";
import { SpeechBubbleArea } from "./components/SpeechBubbleArea";
import { resolveWsUrl, useMochiConnection } from "./hooks/useMochiConnection";
import { useSettingsHydration } from "./hooks/useSettingsHydration";
import { useSidecarStatus } from "./hooks/useSidecarStatus";
import { useI18n } from "./i18n";
import { applyCharacterLayout } from "./layout/applyWindowLayout";
import {
  FALLBACK_LAYOUT,
  computeCharacterLayout,
  type CharacterLayout,
} from "./layout/characterLayout";
import {
  EVENT_ONBOARDING_DONE,
  EVENT_PROVIDERS_CHANGED,
  openPanelWindow,
  type PanelId,
} from "./panelWindow";
import { useConversation } from "./store/conversation";
import { useSettings } from "./store/settings";
import { setupTray } from "./tray";

/** 是否运行于 Tauri 桌面 runtime（dev:web 等浏览器环境无此对象）。 */
const IS_TAURI = "__TAURI_INTERNALS__" in window;

export default function App() {
  // WS 地址随 runtime.json 端口发现更新（M1-S0）：release 下 sidecar 换端口时
  // 桌面壳 emit 就绪事件 → 重新解析 url → useMochiConnection 依 url 变化重连
  const [wsUrl, setWsUrl] = useState(resolveWsUrl);
  useEffect(() => {
    initRuntimePortListener();
    return subscribeRuntimePort(() => setWsUrl(resolveWsUrl()));
  }, []);
  const { sendText, cancelRun } = useMochiConnection(wsUrl);
  const status = useConversation((s) => s.status);
  // release 下 sidecar 异常/重启的可读提示（1.2）；dev/浏览器为 null
  const sidecarHint = useSidecarStatus();
  const { t } = useI18n();
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  // 输入框开关上提到 App：点击角色唤起（CharacterStage.onActivate）
  const [chatOpen, setChatOpen] = useState(false);
  // 浏览器环境（无 Tauri runtime）的面板内联降级状态；桌面端恒为 null
  const [inlinePanel, setInlinePanel] = useState<PanelId | null>(null);
  // 初始设置状态：null = 尚未探测；false = 明确未完成（状态栏提示）；true = 完成
  const [onboardingDone, setOnboardingDone] = useState<boolean | null>(null);
  // 会话内只自动弹一次引导窗：用户关掉后改用状态栏提示，不反复打扰
  const onboardingPrompted = useRef(false);

  // 布局倒置：角色尺寸是窗口尺寸的事实源。初始兜底布局，模型加载完成
  // 切换为按模型包围盒推导的布局并同步 OS 窗口（dev:web 下 no-op）
  const [layout, setLayout] = useState<CharacterLayout>(FALLBACK_LAYOUT);
  const handleModelReady = useCallback(
    (modelWidth: number, modelHeight: number) =>
      setLayout(computeCharacterLayout(modelWidth, modelHeight)),
    [],
  );
  const handleStageFallback = useCallback(() => setLayout(FALLBACK_LAYOUT), []);
  useEffect(() => {
    void applyCharacterLayout(layout);
  }, [layout]);

  // 语言设置事实源在 sidecar config；启动时同步，sidecar 未就绪则重试数次
  useSettingsHydration();

  // 系统托盘（1.4）：菜单文案随语言切换重建（setupTray 幂等）；
  // 非 Tauri 环境整体 no-op
  const locale = useSettings((s) => s.language);
  useEffect(() => {
    if (!IS_TAURI) return;
    let cancelled = false;
    let teardown: (() => void) | null = null;
    void setupTray(locale, { openChat: () => setChatOpen(true) })
      .then((dispose) => {
        if (cancelled) dispose?.();
        else teardown = dispose;
      })
      .catch((err) => {
        console.error("[mochi] 托盘初始化失败：", err);
      });
    return () => {
      cancelled = true;
      teardown?.();
    };
  }, [locale]);

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
          // 桌面端弹独立窗口；浏览器环境降级为窗口内内联向导
          if (IS_TAURI) {
            await openPanelWindow("onboarding");
          } else {
            setInlinePanel("onboarding");
          }
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
    if (IS_TAURI) {
      void openPanelWindow(item);
    } else {
      setInlinePanel(item); // 浏览器环境内联降级（dev:web）
    }
  };

  return (
    <main
      className="app"
      style={
        {
          "--bubble-top": `${layout.bubbleTop}px`,
          "--head-gap": `${layout.headGap}px`,
        } as CSSProperties
      }
    >
      {/* data-tauri-drag-region：Tauri 声明式窗口拖拽（功能清单 1.3）；
          浏览器环境下该属性无副作用。气泡区放在拖拽区外，避免点击气泡误触发拖动 */}
      <div className="app__stage" data-tauri-drag-region>
        <CharacterStage
          onActivate={() => setChatOpen(true)}
          onContextMenu={(x, y) => setMenu({ x, y })}
          onModelReady={handleModelReady}
          onFallback={handleStageFallback}
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

      {/* 浏览器环境（无 Tauri runtime，dev:web）内联降级：面板与向导以模态
          渲染在本窗口内；桌面端走独立窗口，此分支恒不渲染 */}
      {!IS_TAURI && inlinePanel === "onboarding" ? (
        <OnboardingWizard
          onDone={() => {
            setInlinePanel(null);
            setOnboardingDone(true);
          }}
          onOpenSettings={() => setInlinePanel("settings")}
        />
      ) : null}
      {!IS_TAURI && inlinePanel === "settings" ? (
        <SettingsPanel onClose={() => setInlinePanel(null)} />
      ) : null}
      {!IS_TAURI && inlinePanel === "history" ? (
        <HistoryPanel onClose={() => setInlinePanel(null)} />
      ) : null}
      {!IS_TAURI && inlinePanel === "skins" ? (
        <SkinsPanel onClose={() => setInlinePanel(null)} />
      ) : null}
    </main>
  );
}
