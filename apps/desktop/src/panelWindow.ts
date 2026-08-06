/**
 * panelWindow —— 面板独立窗口的打开/复用唯一入口。
 *
 * 功能面板（设置/聊天回忆/衣橱）与初始设置向导不再挤在 320×400 角色窗口内，
 * 而是以 560×640 无边框卡片窗口屏幕居中展示；角色窗口停在原地不受影响。
 * 跨窗口协作走事件：
 * - mochi:panel-navigate：主窗口菜单 → 已打开的面板窗口切换视图；
 * - mochi:onboarding-done：面板窗口 → 主窗口初始设置已完成；
 * - mochi:providers-changed：面板窗口增删 provider → 主窗口重新探测设置状态；
 * - mochi:language-changed：任一窗口切换界面语言 → 其余窗口同步（zustand 不跨窗口）。
 */
import { emit } from "@tauri-apps/api/event";
import { WebviewWindow } from "@tauri-apps/api/webviewWindow";

/** 面板窗口可承载的视图（与 CharacterMenu 菜单项一一对应 + 引导向导）。 */
export type PanelId = "settings" | "history" | "skins" | "onboarding";

export const PANEL_WINDOW_LABEL = "panel";
export const EVENT_PANEL_NAVIGATE = "mochi:panel-navigate";
export const EVENT_ONBOARDING_DONE = "mochi:onboarding-done";
export const EVENT_PROVIDERS_CHANGED = "mochi:providers-changed";
export const EVENT_LANGUAGE_CHANGED = "mochi:language-changed";
export const EVENT_ACTIVE_SESSION_DELETED = "mochi:active-session-deleted";
/** M1-S1：衣橱面板换肤 → 主窗口重建角色舞台（3.3 热切换）。 */
export const EVENT_SKIN_CHANGED = "mochi:skin-changed";

/** 面板窗口尺寸（与主窗口 320×400 区分开，给 provider 行三按钮 + 表单足够空间）。 */
const PANEL_WIDTH = 560;
const PANEL_HEIGHT = 640;

/** 创建中守卫：StrictMode 双调用/快速连续点击时串行化，避免并发重复建窗。 */
let opening: Promise<void> | null = null;

/**
 * 打开（或复用）面板窗口并切到指定视图。
 * 浏览器环境（无 Tauri runtime，如 dev:web）下降级为 no-op。
 */
export function openPanelWindow(id: PanelId): Promise<void> {
  if (!("__TAURI_INTERNALS__" in window)) {
    console.warn(`[mochi] 浏览器环境无 Tauri runtime，跳过面板窗口：${id}`);
    return Promise.resolve();
  }
  const run = (opening ?? Promise.resolve()).then(() => open(id));
  // 存储永不 reject 的链，保证后续调用不被前一次失败拖垮
  opening = run.then(
    () => undefined,
    () => undefined,
  );
  return run;
}

async function open(id: PanelId): Promise<void> {
  const existing = await WebviewWindow.getByLabel(PANEL_WINDOW_LABEL);
  if (existing) {
    await existing.setFocus();
    await emit(EVENT_PANEL_NAVIGATE, { panelId: id });
    return;
  }
  const win = new WebviewWindow(PANEL_WINDOW_LABEL, {
    url: `index.html?panel=${id}`,
    title: "Mochi",
    width: PANEL_WIDTH,
    height: PANEL_HEIGHT,
    center: true,
    resizable: false,
    // 与 character 窗口同置顶层级，避免被置顶的角色窗遮挡
    alwaysOnTop: true,
    // 无边框卡片风：透明 + CSS 圆角/阴影，头部拖拽区见各面板 settings__header
    transparent: true,
    decorations: false,
    shadow: false,
  });
  // 等创建落定再返回：后续 getByLabel 才能可靠判重（构造器异步注册窗口）
  await new Promise<void>((resolve) => {
    win.once("tauri://created", () => resolve());
    win.once("tauri://error", (e) => {
      console.error("[mochi] 面板窗口创建失败:", e);
      resolve();
    });
  });
}
