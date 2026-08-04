/**
 * CharacterMenu —— 右键 Mochi 的上下文菜单（M1-CTX）。
 *
 * webview 自绘（非 Tauri 原生菜单）：与透明窗口卡片风格统一，零 Rust 改动；
 * 系统托盘（S2）走原生，两套职责分离。
 *
 * 交互：光标处弹出（clamp 到窗口内）、点外部/Esc/选中即关、↑↓+Enter 键盘可达。
 */
import { useEffect, useRef, useState } from "react";
import { useI18n } from "../i18n";

export type MenuItemId = "history" | "skins" | "settings";

/** 菜单尺寸（clamp 估算基准，与 styles.css .character-menu 保持一致） */
export const MENU_WIDTH = 176;
export const MENU_HEIGHT = 132;

/** 纯函数：把光标坐标 clamp 到窗口内（含 pad 边距），防菜单溢出 320×400。 */
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
  { id: "skins", icon: "👗", labelKey: "menu.skins" },
  { id: "settings", icon: "⚙️", labelKey: "menu.settings" },
];

export function CharacterMenu({ x, y, onSelect, onClose }: CharacterMenuProps) {
  const { t } = useI18n();
  const [focused, setFocused] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);

  const pos = clampMenuPosition(
    x,
    y,
    MENU_WIDTH,
    MENU_HEIGHT,
    window.innerWidth,
    window.innerHeight,
  );

  // 点击菜单外部关闭
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose();
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
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
    <div
      ref={menuRef}
      className="character-menu"
      role="menu"
      tabIndex={-1}
      style={{ left: pos.x, top: pos.y }}
      onKeyDown={handleKeyDown}
      onMouseLeave={() => setFocused(-1)}
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
  );
}
