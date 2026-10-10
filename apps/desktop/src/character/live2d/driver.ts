/**
 * 渲染驱动层：把 AnimationPlan 应用到 Live2D 模型（状态机输出的执行者）。
 *
 * 参数覆写挂在 internalModel 的 beforeModelUpdate 事件——此时动作/自动眨眼/
 * 呼吸已写完参数而 Core 尚未提交，我们的覆写最后生效，可稳定压过
 * 眨眼（sleeping 闭眼）与动作曲线（表情预设）。
 */
import type { StageHandle } from "./core";
import * as PIXI from "pixi.js";
import type { ParamEnvelopeBinding } from "../../api/skinsClient";
import { compileParamEnvelope } from "./paramEnvelope";
import {
  BODY_ACTION_ENVELOPES,
  EMOTION_PRESETS,
  SLEEPING_PRESET,
  thinkingPoseParams,
  type AnimationPlan,
  type BodyActionEnvelope,
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

/** G1 applyAction 的播放请求（Live2dActionPlan 的结构化子集，避免耦合） */
export interface ActionPlaybackRequest {
  /** 最初请求的动作 id：包络兑底按它查 BODY_ACTION_ENVELOPES */
  requestedId: string;
  motionGroup: string | null;
  paramEnvelope: ParamEnvelopeBinding | null;
}

export interface ActionPlaybackOptions {
  /** cue 起始时刻（Date.now 口径，包络已过时间基准） */
  startedAtMs: number;
  priority: "normal" | "force";
}

export interface CharacterDriver {
  /** 判别字段：组件层按皮肤类型分流驱动（M1-S1 双路径）。 */
  readonly kind: "live2d";
  /** 应用动画计划：切换动作与表情/参数预设，调整目标帧率 */
  applyPlan(plan: AnimationPlan): void;
  /** 播放 one-shot 动作（M-B body 通道）：不打断状态机计划登记，
   *  动作播完后 pixi-live2d-display 自动回落 idle 组（状态 loop 接管） */
  playMotion(group: string, priority: "normal" | "force"): void;
  /**
   * 播放 body 通道语义动作（G1 统一入口，包络执行从组件层下沉至此）：
   * motionGroup 命中 → motion；否则 paramEnvelope 编译执行；再否则按
   * requestedId 查内置包络兑底。畸形声明静默回落，缺参数模型逐参数跳过
   * （首次播放时打点缺失参数，可观测）。包络到期后自然静默，通道由调度层
   * 结算。
   */
  applyAction(request: ActionPlaybackRequest, opts: ActionPlaybackOptions): void;
  /** 参数发现（G1 Phase A）：dump 模型全部参数 id（best-effort，失败返回 []） */
  dumpParamIds(): string[];
  /** 注册每帧参数覆写（口型/视线用）；返回注销函数 */
  addFrameOverride(fn: FrameOverride): () => void;
  /** 写单个参数（按模型实际范围钳制） */
  setParam(id: string, value: number): void;
  /** 命中分区测试（2.4）：视口坐标 → 模型画布坐标 → 分区名数组 */
  hitTestAt(clientX: number, clientY: number): string[];
  readonly params: CubismParamAPI;
  dispose(): void;
}

export function createDriver(stage: StageHandle): CharacterDriver {
  const { model, app } = stage;
  const internal = model.internalModel;
  const params = internal.coreModel as unknown as CubismParamAPI;
  const overrides = new Set<FrameOverride>();
  let plan: AnimationPlan | null = null;
  // G1：body 通道动作包络播放态（applyAction 置入，到期/替换/新 motion 清除）
  let actionEnvelope: {
    env: BodyActionEnvelope;
    requestedId: string;
    startedAtMs: number;
    missingLogged: boolean;
  } | null = null;

  const setParam = (id: string, value: number) => {
    const idx = params.getParameterIndex(id);
    if (idx < 0) return;
    const min = params.getParameterMinimumValue(idx);
    const max = params.getParameterMaximumValue(idx);
    params.setParameterValueById(id, Math.min(max, Math.max(min, value)));
  };

  const presetFor = (expression: ExpressionPlan): Record<string, number> =>
    expression.kind === "params" ? EMOTION_PRESETS[expression.preset] : {};

  const playMotionInternal = (group: string, priority: "normal" | "force") => {
    // index 缺省 = 组内随机；组不存在时库内部静默忽略（调用方已先解析能力）
    void model.motion(group, undefined, MOTION_PRIORITY[priority]);
  };

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
    // 思考姿态：在表情预设之后应用，歪头角度覆写 confused 预设的 AngleZ
    if (plan.thinkingPose) {
      for (const [id, value] of Object.entries(thinkingPoseParams(now))) setParam(id, value);
    }
    if (plan.bodySway) {
      setParam("ParamBodyAngleX", Math.sin(now * 2.2) * 2);
    }
    // 持续打字姿态（批次 3 I1，working 状态）：双臂反相交替 + 低头 + 眼下视。
    // 与 bodySway 互斥使用；包络（overrides）仍最优先，可叠加打断
    if (plan.typing) {
      const cycle = (2 * Math.PI * now) / 0.15; // 150ms 一敲
      setParam("ParamArmLA", 0.35 + 0.15 * Math.sin(cycle));
      setParam("ParamArmRA", 0.35 + 0.15 * Math.sin(cycle + Math.PI));
      setParam("ParamAngleY", -6);
      setParam("ParamEyeBallY", -0.4);
      setParam("ParamBodyAngleY", -2);
    }
    for (const fn of overrides) fn(params, now);
    // body 包络最后应用（G1）：叠在 face 通道与状态机预设之后（最优先），
    // one-shot 微动作不被常规表情覆写冲掉；到期后静默并清除播放态
    if (actionEnvelope) {
      const elapsed = Date.now() - actionEnvelope.startedAtMs;
      if (elapsed >= actionEnvelope.env.durationMs) {
        actionEnvelope = null;
      } else {
        const snapshot = actionEnvelope.env.params(elapsed);
        if (snapshot) {
          if (!actionEnvelope.missingLogged) {
            actionEnvelope.missingLogged = true;
            const missing = Object.keys(snapshot).filter((id) => params.getParameterIndex(id) < 0);
            if (missing.length > 0) {
              console.info(
                `[mochi] envelope ${actionEnvelope.requestedId} 模型缺失参数，逐参数跳过：${missing.join(", ")}`,
              );
            }
          }
          for (const [id, value] of Object.entries(snapshot)) setParam(id, value);
        }
      }
    }
  };
  internal.on("beforeModelUpdate", onBeforeModelUpdate);

  return {
    kind: "live2d",
    params,

    hitTestAt(clientX, clientY) {
      // 视口坐标 → 画布像素（透明窗口无缩放相机，比例换算即可）
      // → toModelPosition（世界→模型逻辑空间）→ hitTest 分区名
      const canvas = app.view as HTMLCanvasElement;
      const rect = canvas.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return [];
      const scaleX = app.renderer.width / rect.width;
      const scaleY = app.renderer.height / rect.height;
      const world = new PIXI.Point((clientX - rect.left) * scaleX, (clientY - rect.top) * scaleY);
      const local = model.toModelPosition(world);
      return model.hitTest(local.x, local.y);
    },

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

    playMotion(group, priority) {
      playMotionInternal(group, priority);
    },

    applyAction(request, opts) {
      if (request.motionGroup) {
        playMotionInternal(request.motionGroup, opts.priority);
        actionEnvelope = null;
        return;
      }
      // 播放优先级（G3/G1）：皮肤声明包络 > 内置兑底；畸形声明编译为 null → 回落
      const env =
        (request.paramEnvelope ? compileParamEnvelope(request.paramEnvelope) : null) ??
        BODY_ACTION_ENVELOPES[request.requestedId] ??
        null;
      if (!env) return;
      actionEnvelope = {
        env,
        requestedId: request.requestedId,
        startedAtMs: opts.startedAtMs,
        missingLogged: false,
      };
    },

    dumpParamIds() {
      // best-effort：框架层 CubismModel 把原始模型藏在 _model（parameterIds: string[]）；
      // 兼容将来直接暴露 parameterIds 或 getParameterId(index) 的版本，全败返回 []
      try {
        const raw = params as unknown as {
          _model?: { parameterIds?: unknown };
          parameterIds?: unknown;
          getParameterId?: (index: number) => string;
        };
        const ids = raw._model?.parameterIds ?? raw.parameterIds;
        if (Array.isArray(ids)) return ids.filter((id): id is string => typeof id === "string");
        if (typeof raw.getParameterId === "function") {
          const count =
            (params as unknown as { getParameterCount?: () => number }).getParameterCount?.() ?? 0;
          const out: string[] = [];
          for (let i = 0; i < count; i += 1) out.push(raw.getParameterId(i));
          return out;
        }
      } catch {
        // 参数发现是增强能力，不阻塞主链路
      }
      return [];
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
      actionEnvelope = null;
    },
  };
}
