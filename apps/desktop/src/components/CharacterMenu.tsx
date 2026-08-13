/**
 * CharacterMenu —— 右键 Mochi 的上下文菜单（M1-CTX）。
 *
 * webview 自绘（非 Tauri 原生菜单）：与透明窗口卡片风格统一，零 Rust 改动；
 * 系统托盘（S2）走原生，两套职责分离。
 *
 * 交互：光标处弹出（clamp 到窗口内）、点外部/Esc/选中即关、↑↓+Enter 键盘可达。
 * 尺寸：固定 160×140（MENU_WIDTH/HEIGHT）——窗口动态贴合角色后不再走
 * 百分比，CSS（styles.css .character-menu 的 px）与本文件的 clamp 估算同源。
 *
 * 点外部关闭走透明 backdrop（菜单下方铺满窗口的隐形层）：菜单打开期间
 * 窗口交互被它接管，点谁都是「先关菜单」，与系统下拉菜单语义一致。
 * backdrop 之上再叠 window 捕获监听 + blur + hasFocus 轮询兜底。
 *
 * 打开时 setFocus 取焦是关键前提：macOS 右键不会让窗口成为 key window，
 * 不取焦则「直接点其他应用」没有失焦事件、blur 不触发，菜单关不掉；
 * 且未持焦窗口的首个左键会被系统吃掉做激活（acceptsFirstMouse），
 * backdrop 也收不到。取焦后这些路径全部恢复正常。
 */
import { useEffect, useRef, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { useI18n } from "../i18n";

export type MenuItemId = "history" | "memory" | "skins" | "settings";

/** 菜单固定像素尺寸：窗口动态贴合角色后尺寸不再等比，固定值保证小窗下可读。
    与 styles.css .character-menu 的 px 取值一一对应；调整任一侧都需同步另一侧。 */
export const MENU_WIDTH = 160;
export const MENU_HEIGHT = 176;

/** 菜单像素尺寸（clamp 定位估算用，与 CSS 固定尺寸一致）。 */
export function getMenuSize(): { width: number; height: number } {
  return { width: MENU_WIDTH, height: MENU_HEIGHT };
}

/** 纯函数：把光标坐标 clamp 到窗口内（含 pad 边距），防菜单溢出动态窗口。 */
export function clampMenuPosition(
  x: number,
  y: number,
  menuW: number,
  menuH: number,
  winW: number,
  winH: number,
  pad = 8,
): { x: number; y: number } {
  return {
    x: Math.min(Math.max(x, pad), Math.max(pad, winW - menuW - pad)),
    y: Math.min(Math.max(y, pad), Math.max(pad, winH - menuH - pad)),
  };
}

interface CharacterMenuProps {
  x: number;
  y: number;
  onSelect: (item: MenuItemId) => void;
  onClose: () => void;
}

interface MenuEntry {
  id: MenuItemId;
  icon: string;
  labelKey: string;
}

// 高频情感入口在前，设置以分隔线隔开殿后（见渲染）
const MENU_ITEMS: MenuEntry[] = [
  { id: "history", icon: "💬", labelKey: "menu.history" },
  { id: "memory", icon: "🧠", labelKey: "menu.memory" },
  { id: "skins", icon: "👗", labelKey: "menu.skins" },
  { id: "settings", icon: "⚙️", labelKey: "menu.settings" },
];

export function CharacterMenu({ x, y, onSelect, onClose }: CharacterMenuProps) {
  const { t } = useI18n();
  const [focused, setFocused] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);

  const winW = window.innerWidth;
  const winH = window.innerHeight;
  const { width: menuW, height: menuH } = getMenuSize();
  const pos = clampMenuPosition(x, y, menuW, menuH, winW, winH);

  // 打开菜单时主动让窗口取焦。
  // macOS 右键不会把窗口变成 key window：若不取焦，之后「直接点其他应用」
  // 不存在失焦过程、blur 永远不触发，菜单就关不掉（取焦后一切正常：
  // 点其他应用 → blur → 关；窗口内点击也能正常送达 backdrop）。
  useEffect(() => {
    if ("__TAURI_INTERNALS__" in window) {
      getCurrentWindow()
        .setFocus()
        .catch(() => {
          /* 取焦失败仅退化回原行为，下方轮询兜底 */
        });
    }
  }, []);

  // 焦点流失轮询兜底：blur 偶发不触发时（如取焦失败、系统级焦点切换），
  // 通过 hasFocus() 的「有→无」跳变关闭。只监听跳变，避免打开即误关。
  useEffect(() => {
    let hadFocus = document.hasFocus();
    const timer = setInterval(() => {
      const hasFocus = document.hasFocus();
      if (hadFocus && !hasFocus) onClose();
      hadFocus = hasFocus;
    }, 400);
    return () => clearInterval(timer);
  }, [onClose]);

  // 兜底关闭（主路径是下方 backdrop）：
  // - 窗口失焦（点了其他应用/桌面）→ 关闭；
  // - 捕获阶段 pointerdown/contextmenu → 关闭（捕获先于 drag.js 的 document
  //   冒泡拦截，事件一定能到达；backdrop 之上的极端路径双保险）。
  useEffect(() => {
    const isOutside = (target: EventTarget | null) =>
      menuRef.current !== null && !menuRef.current.contains(target as Node);
    const onPointerDown = (e: PointerEvent) => {
      if (isOutside(e.target)) onClose();
    };
    const onContextMenu = (e: MouseEvent) => {
      if (isOutside(e.target)) onClose();
    };
    const onBlur = () => onClose();
    window.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("contextmenu", onContextMenu, true);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("contextmenu", onContextMenu, true);
      window.removeEventListener("blur", onBlur);
    };
  }, [onClose]);

  useEffect(() => {
    menuRef.current?.focus();
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    switch (e.key) {
      case "Escape":
        e.preventDefault();
        onClose();
        break;
      case "ArrowDown":
        e.preventDefault();
        setFocused((i) => (i + 1) % MENU_ITEMS.length);
        break;
      case "ArrowUp":
        e.preventDefault();
        setFocused((i) => (i - 1 + MENU_ITEMS.length) % MENU_ITEMS.length);
        break;
      case "Enter":
        e.preventDefault();
        onSelect(MENU_ITEMS[focused].id);
        break;
    }
  };

  return (
    <>
      {/* 透明 backdrop：菜单打开期间接管菜单外的全部窗口交互，
          任意按下/右键都关闭菜单（系统下拉菜单语义）。z-index 低于菜单，
          不带 data-tauri-drag-region，不会触发 drag.js 的窗口拖动。 */}
      <div
        className="character-menu-backdrop"
        onMouseDown={onClose}
        onContextMenu={(e) => {
          e.preventDefault();
          onClose();
        }}
      />
      <div
        ref={menuRef}
        className="character-menu"
        role="menu"
        tabIndex={-1}
        style={{ left: pos.x, top: pos.y }}
        onKeyDown={handleKeyDown}
        onMouseLeave={() => setFocused(-1)}
        onContextMenu={(e) => e.preventDefault()}
      >
        {MENU_ITEMS.map((item, i) => (
          <div key={item.id}>
            {item.id === "settings" ? <div className="character-menu__divider" /> : null}
            <button
              type="button"
              role="menuitem"
              className={`character-menu__item${focused === i ? " character-menu__item--focused" : ""}`}
              onMouseEnter={() => setFocused(i)}
              onClick={() => onSelect(item.id)}
            >
              <span className="character-menu__icon" aria-hidden>
                {item.icon}
              </span>
              {t(item.labelKey)}
            </button>
          </div>
        ))}
      </div>
    </>
  );
}
