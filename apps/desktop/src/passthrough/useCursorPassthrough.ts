/**
 * useCursorPassthrough —— 透明区域动态鼠标穿透（「点击区域过大」修复的窗口层）。
 *
 * 窗口矩形大于可见角色，透明区域若照常接收事件会挡住下层应用。此 hook 以
 * 固定间隔轮询全局光标位置（物理 px）+ 窗口矩形缓存，换算出窗口内 CSS px
 * 坐标后交给 getInteractiveAt 判定：
 *   - 命中角色本体 / dock / 气泡 / 菜单等 UI → 正常接收事件；
 *   - 处于透明区域 → setIgnoreCursorEvents(true)，点击穿透到桌面。
 *
 * 为何轮询而非 mousemove：Tauri 的 setIgnoreCursorEvents 无 forward 选项
 * （macOS 转发 mousemove），窗口一旦忽略事件就收不到 mousemove，无法感知
 * 光标回到角色上；轮询 cursorPosition（全局坐标）在忽略状态下依然可用，
 * 两平台行为一致。60ms 间隔 + 矩形缓存（拖动中每 tick 刷新）平衡时延与 IPC。
 *
 * 浏览器环境（dev:web 无 Tauri runtime）整体 no-op。
 * 光标不在窗口内或按住鼠标（拖拽/输入中）时不做切换，避免交互中途被穿透。
 */
import { useEffect } from "react";
import { cursorPosition, getCurrentWindow } from "@tauri-apps/api/window";
import { reportCursor } from "./cursorTracker";

/** 轮询间隔（ms）：穿透切换时延上限。 */
const POLL_MS = 60;
/** 窗口矩形缓存寿命（ms）：位置只在拖动/移动时变化，光标在窗内时逐 tick 刷新。 */
const RECT_REFRESH_MS = 400;

interface WindowRect {
  x: number;
  y: number;
  w: number;
  h: number;
  factor: number;
  at: number;
}

export function useCursorPassthrough(getInteractiveAt: (x: number, y: number) => boolean): void {
  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    const win = getCurrentWindow();
    let ignoring = false;
    let hardFailed = false; // setIgnoreCursorEvents 硬错误（如权限缺失）后停轮询
    let rect: WindowRect | null = null;
    let buttonsDown = 0;

    const onDown = () => {
      buttonsDown = 1;
    };
    // 单鼠标语义：pointerup 即全部释放（直接归零而非递减）——拖拽会话可能
    // 吞掉拖动结束的 mouseup，若用计数去递减会永久卡在“按住”而禁用穿透；
    // 归零写法下一次真实点击的 up 即可自愈
    const onUp = () => {
      buttonsDown = 0;
    };
    const onBlur = () => {
      buttonsDown = 0;
    };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("pointerup", onUp, true);
    window.addEventListener("pointercancel", onUp, true);
    window.addEventListener("blur", onBlur);

    const setIgnoring = async (next: boolean) => {
      if (next === ignoring) return;
      try {
        await win.setIgnoreCursorEvents(next);
        ignoring = next;
        toggles += 1;
        console.info(`[mochi] 鼠标穿透：${next ? "放行透明区（穿透）" : "恢复接收（角色/UI）"}`);
      } catch (err) {
        // 权限缺失等硬错误只告警一次，避免轮询刷屏；之后停轮询
        console.error("[mochi] 鼠标穿透切换失败（检查 capabilities 权限）：", err);
        hardFailed = true;
      }
    };

    // §诊断：每 tick 发布状态（devtools 控制台读 __mochiPassthrough，
    // 同 __mochiStats 模式）；toggles 恒 0 = 穿透从未触发，指向掩码/判定问题
    let toggles = 0;
    let lastEval: Record<string, unknown> | null = null;
    const publishDebug = (
      cur: { x: number; y: number },
      r: WindowRect,
      interactive: boolean | null,
    ) => {
      lastEval = {
        cursor: cur,
        winRect: r,
        local: { x: (cur.x - r.x) / r.factor, y: (cur.y - r.y) / r.factor },
        interactive,
        ignoring,
        toggles,
        hardFailed,
        buttonsDown,
        at: performance.now(),
      };
      (window as unknown as { __mochiPassthrough?: unknown }).__mochiPassthrough = lastEval;
    };

    const refreshRect = async (now: number): Promise<WindowRect> => {
      const [factor, pos, size] = await Promise.all([
        win.scaleFactor(),
        win.outerPosition(),
        win.outerSize(),
      ]);
      // 无边框透明窗口 outer ≈ client；物理尺寸/坐标除以 factor 回逻辑 px
      rect = { x: pos.x, y: pos.y, w: size.width, h: size.height, factor, at: now };
      return rect;
    };

    const tick = async () => {
      if (hardFailed) return;
      try {
        const now = performance.now();
        const cur = await cursorPosition();
        // 缓存命中策略：无缓存/已过期/光标在窗内（拖动中位置逐帧变）→ 刷新；
        // 光标在窗外的短窗口内用缓存即可（下一步本就早退）
        const fresh = rect && now - rect.at <= RECT_REFRESH_MS ? rect : null;
        const r = fresh && !inside(fresh, cur) ? fresh : await refreshRect(now);
        // 追鼠标事实源：无条件上报（窗外坐标可为负/越界，消费方 normalizeGaze
        // clamp 到 ±1——角色保持朝窗外光标方向看）；拖拽中上报无害且更跟手
        reportCursor((cur.x - r.x) / r.factor, (cur.y - r.y) / r.factor);
        if (!inside(r, cur)) {
          void setIgnoring(false); // 窗外：恢复接收，避免状态悬挂
          publishDebug(cur, r, null);
          return;
        }
        if (buttonsDown > 0) return; // 拖拽/按住中不切换
        const lx = (cur.x - r.x) / r.factor;
        const ly = (cur.y - r.y) / r.factor;
        const interactive = getInteractiveAt(lx, ly);
        publishDebug(cur, r, interactive);
        void setIgnoring(!interactive);
      } catch {
        // IPC 失败：跳过本 tick
      }
    };

    const timer = window.setInterval(() => {
      void tick();
    }, POLL_MS);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("pointerup", onUp, true);
      window.removeEventListener("pointercancel", onUp, true);
      window.removeEventListener("blur", onBlur);
      // 卸载必恢复接收，避免窗口永久穿透不可交互
      void win.setIgnoreCursorEvents(false).catch(() => {});
    };
  }, [getInteractiveAt]);
}

function inside(r: WindowRect, p: { x: number; y: number }): boolean {
  return p.x >= r.x && p.x < r.x + r.w && p.y >= r.y && p.y < r.y + r.h;
}
