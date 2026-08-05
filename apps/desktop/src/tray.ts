/**
 * 系统托盘快捷菜单（功能清单 1.4，M1-S0）。
 *
 * 经 Tauri v2 JS API（TrayIcon/Menu）构建：文案与面板共用 i18n 事实源，
 * 语言切换由调用方重建菜单；「退出」经事件桥到 Rust
 * （mochi:tray-quit → app.exit(0) 触发 RunEvent::Exit 回收 sidecar，ADR-0001）。
 * 浏览器环境（dev:web）整体 no-op。
 *
 * 菜单项：显隐 Mochi / 打开对话 / 静音（勾选态，落盘 [voice].muted）/ 退出。
 */
import { emit } from "@tauri-apps/api/event";
import { Image } from "@tauri-apps/api/image";
import { CheckMenuItem, Menu, MenuItem } from "@tauri-apps/api/menu";
import { TrayIcon } from "@tauri-apps/api/tray";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { configApi } from "./api/configClient";
import { translate, type Language } from "./i18n";

export const TRAY_ID = "mochi-tray";

/** 托盘「退出」事件：Rust 侧监听后 app.exit(0)（lib.rs）。 */
export const TRAY_QUIT_EVENT = "mochi:tray-quit";

export interface TrayCallbacks {
  /** 「打开对话」：角色窗口取焦并唤起输入条（由 App 提供 setChatOpen）。 */
  openChat: () => void;
}

/**
 * 构建托盘菜单并返回拆解函数；非 Tauri 环境返回 null。
 * 重复构建（StrictMode 双挂载 / 语言切换）先移除旧托盘，幂等。
 */
export async function setupTray(
  locale: Language,
  callbacks: TrayCallbacks,
): Promise<(() => void) | null> {
  if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) return null;

  if ((await TrayIcon.getById(TRAY_ID)) !== null) {
    await TrayIcon.removeById(TRAY_ID);
  }

  // macOS 用 template 剪影（菜单栏跟随系统深浅色）；其余平台用彩色应用图标
  const isMac = navigator.platform.toLowerCase().includes("mac");
  const iconBytes = new Uint8Array(
    await (await fetch(isMac ? "/tray-icon-template.png" : "/tray-icon-color.png")).arrayBuffer(),
  );

  const t = (key: string) => translate(locale, key);
  const win = getCurrentWindow();

  const showHide = await MenuItem.new({
    text: t("tray.showHide"),
    action: () => {
      void (async () => {
        if (await win.isVisible()) {
          await win.hide();
        } else {
          await win.show();
          await win.setFocus();
        }
      })();
    },
  });

  const openChat = await MenuItem.new({
    text: t("tray.openChat"),
    action: () => {
      void (async () => {
        await win.show();
        await win.setFocus();
        callbacks.openChat();
      })();
    },
  });

  // sidecar 未就绪时按未静音起步；点击后以配置为事实源
  const mutedNow = await configApi
    .getVoice()
    .then((voice) => voice.muted)
    .catch(() => false);
  const mute = await CheckMenuItem.new({
    text: t("tray.mute"),
    checked: mutedNow,
    action: () => {
      void (async () => {
        // 原生点击已翻转勾选态：读新值持久化，失败回滚勾选
        const next = await mute.isChecked();
        try {
          await configApi.putVoice({ muted: next });
        } catch {
          await mute.setChecked(!next);
        }
      })();
    },
  });

  const quit = await MenuItem.new({
    text: t("tray.quit"),
    action: () => {
      void emit(TRAY_QUIT_EVENT);
    },
  });

  const menu = await Menu.new({ items: [showHide, openChat, mute, quit] });
  await TrayIcon.new({
    id: TRAY_ID,
    icon: await Image.fromBytes(iconBytes),
    iconAsTemplate: isMac,
    tooltip: "Mochi",
    menu,
  });

  return () => {
    void TrayIcon.removeById(TRAY_ID);
  };
}
