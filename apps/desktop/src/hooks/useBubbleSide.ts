/**
 * useBubbleSide —— 决定回复气泡出现在角色头部的哪一侧。
 *
 * 规则：气泡展示在角色旁边**屏幕空间更充足**的一侧——窗口靠近屏幕左缘
 * （左侧空间不够）时气泡在头部右侧，靠近右缘时在头部左侧，贴近头部并
 * 以尾三角水平指向头部，明确「Mochi 说的话」；同时避免气泡贴死屏幕边缘。
 * 窗口移动后重新计算：Tauri 环境以官方 onMoved 事件为权威（DOM move
 * 事件在 webview 中不保证触发），浏览器 dev 环境退回 window "move"/
 * "resize" 事件兜底。
 *
 * Tauri API 走静态导入（包内其他模块已静态引入 window，动态导入无代码
 * 分割收益，vite 会告警）；浏览器环境隔离由运行时守卫承担。
 */
import { getCurrentWindow } from "@tauri-apps/api/window";
import { useEffect, useState } from "react";

export type BubbleSide = "left" | "right";

/** 纯函数便于单测：角色（窗口中心）离屏幕哪条边更近，气泡就去另一侧。 */
export function resolveBubbleSide(
  windowScreenX: number,
  windowWidth: number,
  screenWidth: number,
): BubbleSide {
  const charCenterX = windowScreenX + windowWidth / 2;
  // 靠屏幕左半 → 左侧空间不够 → 气泡在头部右侧；右半反之
  return charCenterX <= screenWidth / 2 ? "right" : "left";
}

function computeSide(): BubbleSide {
  if (typeof window === "undefined") return "right";
  return resolveBubbleSide(window.screenX, window.innerWidth, window.screen.width);
}

export function useBubbleSide(): BubbleSide {
  const [side, setSide] = useState<BubbleSide>(computeSide);

  useEffect(() => {
    const update = () => setSide(computeSide());
    window.addEventListener("move", update);
    window.addEventListener("resize", update);

    let unlisten: (() => void) | null = null;
    let cancelled = false;
    if ("__TAURI_INTERNALS__" in window) {
      void getCurrentWindow()
        .onMoved(update)
        .then((u) => {
          if (cancelled) u();
          else unlisten = u;
        });
    }
    return () => {
      cancelled = true;
      unlisten?.();
      window.removeEventListener("move", update);
      window.removeEventListener("resize", update);
    };
  }, []);

  return side;
}
