/**
 * Live2D 动画状态机（功能清单 2.2：6 状态 × 情绪映射）。
 *
 * 纯函数层：(characterState, emotion, 模型档案) → 动画计划；
 * 组件层（CharacterStage）负责应用计划。纯函数便于 vitest 全组合覆盖。
 *
 * 表情策略（ADR-0003 D3）：模型带 exp3 → 用表情文件；
 * Hiyori 无 exp3 → 参数预设（数值为归一化 [-1, 1]，组件层按模型实际范围写参）。
 */
import type { CharacterState, Emotion } from "@mochi/protocol";

/** 动作优先级（组件层映射到 pixi-live2d-display 的 MotionPriority） */
export type MotionPriorityLevel = "idle" | "normal" | "force";

export type ExpressionPlan = { kind: "file"; name: string } | { kind: "params"; preset: Emotion };

/** 模型实际能力档案（加载后从 settings 读出） */
export interface ModelProfile {
  motionGroups: readonly string[];
  expressions: readonly string[];
}

export interface AnimationPlan {
  /** 要播放的动作组；null = 不切换动作 */
  motionGroup: string | null;
  motionPriority: MotionPriorityLevel;
  expression: ExpressionPlan;
  /** 强制闭眼（sleeping；驱动层直写双眼开合参数，压过自动眨眼） */
  eyesClosed: boolean;
  /** 口型驱动（2.3，仅说话期） */
  mouthEnabled: boolean;
  /** 视线跟随（2.4；sleeping/error 禁用） */
  gazeEnabled: boolean;
  /** 视线纵向偏移（思考时上瞟） */
  gazeOffsetY: number;
  /** 身体微晃（working） */
  bodySway: boolean;
  /** 目标帧率（性能护栏，Phase 7 使用） */
  tickerFps: 30 | 60;
}

/**
 * 情绪 → 参数预设（Hiyori 参数集，归一化 [-1, 1]）。
 * 数值为初版估计，E2E 阶段目测微调；键名即 Cubism 参数 ID。
 */
export const EMOTION_PRESETS: Record<Emotion, Record<string, number>> = {
  neutral: {},
  happy: { ParamMouthForm: 1, ParamEyeLSmile: 1, ParamEyeRSmile: 1 },
  sad: { ParamAngleZ: -10, ParamBrowLY: -0.5, ParamBrowRY: -0.5, ParamMouthForm: -1 },
  confused: { ParamAngleZ: 8, ParamBrowLAngle: -0.3, ParamBrowRAngle: 0.3 },
  surprised: { ParamBrowLY: 0.7, ParamBrowRY: 0.7, ParamAngleZ: -3 },
  embarrassed: { ParamCheek: 1, ParamAngleZ: -5, ParamMouthForm: 0.5 },
  angry: { ParamBrowLAngle: -0.6, ParamBrowRAngle: -0.6, ParamMouthForm: -1, ParamAngleZ: 3 },
};

/** 休眠专用预设：闭眼由组件层直写双眼开合参数实现，这里只配眉眼放松 */
export const SLEEPING_PRESET: Record<string, number> = {
  ParamBrowLY: -0.3,
  ParamBrowRY: -0.3,
  ParamMouthForm: 0,
};

interface StateRule {
  /** 按偏好顺序尝试的动作组（取模型实际拥有的第一个） */
  motionPreference: readonly string[];
  motionPriority: MotionPriorityLevel;
  /** 情绪表情是否被状态覆盖（error/sleeping 强制自己的表情） */
  forcedEmotion?: Emotion;
  eyesClosed: boolean;
  mouthEnabled: boolean;
  gazeEnabled: boolean;
  gazeOffsetY: number;
  bodySway: boolean;
  tickerFps: 30 | 60;
}

/** 6 状态规则表：动作组偏好均回退到 Idle（Hiyori 无专用组，ADR-0003 D4） */
export const STATE_RULES: Record<CharacterState, StateRule> = {
  idle: {
    motionPreference: ["Idle"],
    motionPriority: "idle",
    eyesClosed: false,
    mouthEnabled: false,
    gazeEnabled: true,
    gazeOffsetY: 0,
    bodySway: false,
    tickerFps: 30,
  },
  talking: {
    motionPreference: ["Idle"],
    motionPriority: "normal",
    eyesClosed: false,
    mouthEnabled: true,
    gazeEnabled: true,
    gazeOffsetY: 0,
    bodySway: false,
    tickerFps: 60,
  },
  thinking: {
    motionPreference: ["Idle"],
    motionPriority: "normal",
    forcedEmotion: "confused",
    eyesClosed: false,
    mouthEnabled: false,
    gazeEnabled: true,
    gazeOffsetY: 0.4,
    bodySway: false,
    tickerFps: 60,
  },
  working: {
    motionPreference: ["Idle"],
    motionPriority: "normal",
    eyesClosed: false,
    mouthEnabled: false,
    gazeEnabled: true,
    gazeOffsetY: 0,
    bodySway: true,
    tickerFps: 60,
  },
  error: {
    motionPreference: ["Idle"],
    motionPriority: "force",
    forcedEmotion: "sad",
    eyesClosed: false,
    mouthEnabled: false,
    gazeEnabled: false,
    gazeOffsetY: -0.2,
    bodySway: false,
    tickerFps: 30,
  },
  sleeping: {
    motionPreference: ["Idle"],
    motionPriority: "force",
    forcedEmotion: "neutral",
    eyesClosed: true,
    mouthEnabled: false,
    gazeEnabled: false,
    gazeOffsetY: 0,
    bodySway: false,
    tickerFps: 30,
  },
};

function pickMotionGroup(
  preference: readonly string[],
  available: readonly string[],
): string | null {
  for (const group of preference) {
    if (available.includes(group)) return group;
  }
  return available.length > 0 ? available[0] : null;
}

/** 情绪 → 表情计划：exp3 优先，缺则参数预设 */
function resolveExpression(emotion: Emotion, profile: ModelProfile): ExpressionPlan {
  if (profile.expressions.includes(emotion)) {
    return { kind: "file", name: emotion };
  }
  return { kind: "params", preset: emotion };
}

/** 状态机主入口：计算当前 (状态, 情绪) 的动画计划 */
export function resolveAnimation(
  state: CharacterState,
  emotion: Emotion | null,
  profile: ModelProfile,
): AnimationPlan {
  const rule = STATE_RULES[state];
  const effectiveEmotion = rule.forcedEmotion ?? emotion ?? "neutral";
  return {
    motionGroup: pickMotionGroup(rule.motionPreference, profile.motionGroups),
    motionPriority: rule.motionPriority,
    expression: resolveExpression(effectiveEmotion, profile),
    eyesClosed: rule.eyesClosed,
    mouthEnabled: rule.mouthEnabled,
    gazeEnabled: rule.gazeEnabled,
    gazeOffsetY: rule.gazeOffsetY,
    bodySway: rule.bodySway,
    tickerFps: rule.tickerFps,
  };
}

/** Hiyori PRO t11 实际能力档案（加载时可与运行时 dump 结果核对） */
export const HIYORI_PROFILE: ModelProfile = {
  motionGroups: ["Idle", "Flick", "FlickDown", "FlickUp", "Tap", "Tap@Body", "Flick@Body"],
  expressions: [],
};
