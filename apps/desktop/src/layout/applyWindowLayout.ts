/**
 * applyWindowLayout —— 把角色布局同步到 OS 窗口（Tauri API 层）。
 *
 * 顺序固定先 setSize 后 setPosition：setPosition 以脚底锚定
 * （anchorBottomY）补偿高度变化，角色脚底在屏幕上不跳动。
 * dev:web 等浏览器环境无 Tauri runtime，整体 no-op（DOM 布局自行适应）。
 */
import { getCurrentWindow } from "@tauri-apps/api/window";
import { LogicalSize, PhysicalPosition } from "@tauri-apps/api/dpi";
import { anchorBottomY, type CharacterLayout } from "./characterLayout";

export async function applyCharacterLayout(layout: CharacterLayout): Promise<void> {
  if (!("__TAURI_INTERNALS__" in window)) return;
  const win = getCurrentWindow();
  const [factor, pos, oldSize] = await Promise.all([
    win.scaleFactor(),
    win.outerPosition(),
    win.outerSize(),
  ]);
  await win.setSize(new LogicalSize(layout.winW, layout.winH));
  // 无边框窗口 outer ≈ inner；scaleFactor 把逻辑高换回物理高做底边锚定
  const newOuterH = Math.round(layout.winH * factor);
  await win.setPosition(
    new PhysicalPosition(pos.x, anchorBottomY(pos.y, oldSize.height, newOuterH)),
  );
}
