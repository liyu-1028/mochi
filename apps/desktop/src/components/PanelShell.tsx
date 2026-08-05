/**
 * PanelShell —— 面板独立窗口的根组件（main.tsx 按 ?panel=xxx 分流渲染）。
 *
 * 复用 SettingsPanel / HistoryPanel / SkinsPanel / OnboardingWizard 组件（JSX 不变），
 * .panel-shell CSS 覆写让 .settings-overlay/.settings 模态样式铺满整窗呈现卡片形态；
 * 监听 mochi:panel-navigate，与角色窗口右键菜单联动切换视图（复用窗口不新建）。
 */
import { useEffect, useState } from "react";
import { emit, listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { useSettingsHydration } from "../hooks/useSettingsHydration";
import { EVENT_ONBOARDING_DONE, EVENT_PANEL_NAVIGATE, type PanelId } from "../panelWindow";
/* settings.css 由 main.tsx 全局导入（App 内联降级与 PanelShell 共用） */
import { HistoryPanel } from "./HistoryPanel";
import { OnboardingWizard } from "./OnboardingWizard";
import { SettingsPanel } from "./SettingsPanel";
import { SkinsPanel } from "./SkinsPanel";

interface PanelShellProps {
  initialPanel: PanelId;
}

export function PanelShell({ initialPanel }: PanelShellProps) {
  const [panel, setPanel] = useState<PanelId>(initialPanel);
  // 语言事实源在 sidecar；面板窗口是独立 JS 上下文，需自行 hydrate
  useSettingsHydration();

  // 角色窗口菜单再次选择时切换本窗口视图（见 panelWindow.openPanelWindow）
  useEffect(() => {
    const unlisten = listen<{ panelId: PanelId }>(EVENT_PANEL_NAVIGATE, (e) => {
      setPanel(e.payload.panelId);
    });
    return () => {
      unlisten.then((fn) => fn());
    };
  }, []);

  const closeWindow = () => {
    void getCurrentWindow().close();
  };

  return (
    <div className="panel-shell">
      {panel === "settings" ? <SettingsPanel onClose={closeWindow} /> : null}
      {panel === "history" ? <HistoryPanel onClose={closeWindow} /> : null}
      {panel === "skins" ? <SkinsPanel onClose={closeWindow} /> : null}
      {panel === "onboarding" ? (
        <OnboardingWizard
          onDone={() => {
            void emit(EVENT_ONBOARDING_DONE);
            closeWindow();
          }}
          onOpenSettings={() => setPanel("settings")}
        />
      ) : null}
    </div>
  );
}
