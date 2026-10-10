/**
 * powerGuard —— 性能护栏降档决策（2.6，纯函数便于单测）。
 *
 * 三档帧率阶梯 60 → 30 → 15：
 * - 自动降档：滚动 5s 窗口平均帧耗时 > DOWNGRADE_MS（40ms，即 <25fps）
 *   → 降一档并暂停装饰性动画（漂浮/呼吸/微晃）；< RECOVER_MS（25ms）
 *   → 升一档恢复；
 * - 省电模式（设置-通用手动开关）：钉死最低档 + 暂停装饰动画，不看负载。
 *
 * 回滞区间（25–40ms）双阈值防抖：负载临界时不反复横跳。
 * 决策输出仅 fps 档位与动画开关，应用侧由 CharacterStage 落到
 * ticker.maxFPS 与动画 plan 掩码——对话链路与渲染解耦，降档不影响功能。
 */

export type FpsLevel = 0 | 1 | 2;

export const FPS_LADDER = [60, 30, 15] as const;

/** 平均帧耗时降档阈值：>40ms（约 <25fps）视为持续过载。 */
export const DOWNGRADE_MS = 40;

/** 平均帧耗时回升阈值：<25ms（约 >40fps 余量）才升档（回滞防抖）。 */
export const RECOVER_MS = 25;

/** 决策窗口：近 WINDOW_MS 内样本求均值（持续 5s 过载才降）。 */
export const WINDOW_MS = 5000;

/** 滚动样本窗：push 进窗、淘汰过期，average() 返回窗口均值（无样本为 null）。 */
export function createSampleWindow(windowMs = WINDOW_MS) {
  let samples: Array<[time: number, ms: number]> = [];
  return {
    push(ms: number, now: number): void {
      samples.push([now, ms]);
      const cutoff = now - windowMs;
      let first = samples.findIndex(([t]) => t >= cutoff);
      if (first === -1) first = samples.length;
      if (first > 0) samples = samples.slice(first);
    },
    average(): number | null {
      if (samples.length === 0) return null;
      return samples.reduce((sum, [, ms]) => sum + ms, 0) / samples.length;
    },
  };
}

/** 下一档位：省电钉最低档；过载降一档；空闲升一档；回滞区间保持。 */
export function nextFpsLevel(
  current: FpsLevel,
  avgMs: number | null,
  powerSave: boolean,
): FpsLevel {
  if (powerSave) return 2;
  if (avgMs === null) return current;
  if (avgMs > DOWNGRADE_MS) return Math.min(current + 1, 2) as FpsLevel;
  if (avgMs < RECOVER_MS && current > 0) return (current - 1) as FpsLevel;
  return current;
}

/** 档位生效帧率：高档取状态计划基准（idle 30 / talking 60），中档封 30，低档 15。 */
export function effectiveFps(baseFps: number, level: FpsLevel): number {
  if (level === 2) return FPS_LADDER[2];
  if (level === 1) return Math.min(baseFps, FPS_LADDER[1]);
  return baseFps;
}

/** 装饰性动画（漂浮/呼吸/微晃）在降档后暂停：保对话口型/表情等功能动画。 */
export function decorationsPaused(level: FpsLevel): boolean {
  return level >= 1;
}
