/**
 * 渲染驱动层：把 AnimationPlan 应用到 Live2D 模型（状态机输出的执行者）。
 *
 * 参数覆写挂在 internalModel 的 beforeModelUpdate 事件——此时动作/自动眨眼/
 * 呼吸已写完参数而 Core 尚未提交，我们的覆写最后生效，可稳定压过
 * 眨眼（sleeping 闭眼）与动作曲线（表情预设）。
 */
import type { StageHandle } from "./core";
import {
  EMOTION_PRESETS,
  SLEEPING_PRESET,
  type AnimationPlan,
  type ExpressionPlan,
} from "./stateMachine";

// pixi-live2d-display MotionPriority 枚举数值（SDK 规范恒定）；
// 本地常量化避免顶层求值库模块（此时 Cubism Core 可能未就绪）
const MOTION_PRIORITY = { idle: 1, normal: 2, force: 3 } as const;

/** Cubism 核心参数 API 结构化类型（库类型中 coreModel 为 object，自行收窄） */
export interface CubismParamAPI {
  getParameterIndex(id: string): number;
  getParameterMinimumValue(index: number): number;
  getParameterMaximumValue(index: number): number;
  setParameterValueById(id: string, value: number, weight?: number): void;
}

export type FrameOverride = (params: CubismParamAPI, nowSec: number) => void;

export interface CharacterDriver {
  /** 应用动画计划：切换动作与表情/参数预设，调整目标帧率 */
  applyPlan(plan: AnimationPlan): void;
  /** 注册每帧参数覆写（口型/视线用）；返回注销函数 */
  addFrameOverride(fn: FrameOverride): () => void;
  /** 写单个参数（按模型实际范围钳制） */
  setParam(id: string, value: number): void;
  readonly params: CubismParamAPI;
  dispose(): void;
}

export function createDriver(stage: StageHandle): CharacterDriver {
  const { model, app } = stage;
  const internal = model.internalModel;
  const params = internal.coreModel as unknown as CubismParamAPI;
  const overrides = new Set<FrameOverride>();
  let plan: AnimationPlan | null = null;

  const setParam = (id: string, value: number) => {
    const idx = params.getParameterIndex(id);
    if (idx < 0) return;
    const min = params.getParameterMinimumValue(idx);
    const max = params.getParameterMaximumValue(idx);
    params.setParameterValueById(id, Math.min(max, Math.max(min, value)));
  };

  const presetFor = (expression: ExpressionPlan): Record<string, number> =>
    expression.kind === "params" ? EMOTION_PRESETS[expression.preset] : {};

  const onBeforeModelUpdate = () => {
    if (!plan) return;
    const now = performance.now() / 1000;
    if (plan.eyesClosed) {
      // 休眠：专用预设 + 直写双眼闭合，压过自动眨眼
      for (const [id, value] of Object.entries(SLEEPING_PRESET)) setParam(id, value);
      setParam("ParamEyeLOpen", 0);
      setParam("ParamEyeROpen", 0);
    } else {
      for (const [id, value] of Object.entries(presetFor(plan.expression))) setParam(id, value);
    }
    if (plan.bodySway) {
      setParam("ParamBodyAngleX", Math.sin(now * 2.2) * 2);
    }
    for (const fn of overrides) fn(params, now);
  };
  internal.on("beforeModelUpdate", onBeforeModelUpdate);

  return {
    params,

    applyPlan(next) {
      const prev = plan;
      plan = next;
      app.ticker.maxFPS = next.tickerFps;
      const motionChanged =
        prev === null ||
        prev.motionGroup !== next.motionGroup ||
        prev.motionPriority !== next.motionPriority;
      if (next.motionGroup && motionChanged) {
        // index 缺省 = 组内随机选一个
        void model.motion(next.motionGroup, undefined, MOTION_PRIORITY[next.motionPriority]);
      }
      if (next.expression.kind === "file") {
        void model.expression(next.expression.name);
      }
    },

    addFrameOverride(fn) {
      overrides.add(fn);
      return () => overrides.delete(fn);
    },

    setParam,

    dispose() {
      internal.off("beforeModelUpdate", onBeforeModelUpdate);
      overrides.clear();
      plan = null;
    },
  };
}
