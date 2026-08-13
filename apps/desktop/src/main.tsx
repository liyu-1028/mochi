import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { PanelShell } from "./components/PanelShell";
import type { PanelId } from "./panelWindow";
import "./styles.css";
/* 面板/向导样式全局导入：桌面端由 PanelShell 窗口使用，浏览器 dev:web
   的内联降级（App.tsx IS_TAURI 分支）同样需要 */
import "./styles/settings.css";

/** 面板窗口视图白名单（与 panelWindow.PanelId 一致）。 */
const PANEL_IDS: readonly string[] = ["settings", "history", "memory", "skins", "onboarding"];

/**
 * 入口分流：面板独立窗口以 index.html?panel=xxx 打开，渲染 PanelShell；
 * 无 panel 参数（角色主窗口 / 浏览器 dev）渲染 App。
 * 参数非法时回退 settings，避免面板窗口渲染角色界面。
 */
function resolvePanelId(): PanelId | null {
  const raw = new URLSearchParams(window.location.search).get("panel");
  if (raw === null) return null;
  return PANEL_IDS.includes(raw) ? (raw as PanelId) : "settings";
}

const panelId = resolvePanelId();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>{panelId ? <PanelShell initialPanel={panelId} /> : <App />}</React.StrictMode>,
);

// 启动里程碑打点（performance.now 相对页面 timeOrigin）：1.1 冷启动验收用
console.info(`[mochi] app-mounted +${Math.round(performance.now())}ms`);
