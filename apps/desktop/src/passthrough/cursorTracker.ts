/**
 * cursorTracker —— 窗口内光标位置的事实源（追鼠标交互的公共上游）。
 *
 * 双源上报：
 * - mousemove（浏览器/dev:web 与桌面端窗口接收事件时的细粒度路径）；
 * - useCursorPassthrough 轮询（桌面端光标处于穿透忽略区/窗外时依然可用，
 *   这是穿透改造后 mousemove 收不到事件时的关键补充）。
 *
 * 消费方（Live2D 视线 / 静态皮肤 gazeLean）每帧读取，自行 lerp 平滑；
 * 坐标为窗口内 CSS px（原点左上），窗外值可能为负/越界，由消费方 clamp。
 */

interface CursorSample {
  x: number;
  y: number;
  at: number;
  /** 是否收到过任何样本（未收到时消费方用中心默认值）。 */
  fresh: boolean;
}

let last: CursorSample = { x: 0, y: 0, at: 0, fresh: false };

export function reportCursor(x: number, y: number): void {
  last = { x, y, at: performance.now(), fresh: true };
}

export function getCursor(): Readonly<CursorSample> {
  return last;
}
