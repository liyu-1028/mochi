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
  /** 模型全部参数 id（G1 Phase A；未 dump 时为空数组——能力核对降级为跳过） */
  paramIds?: readonly string[];
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
  /** 思考姿态（2.2 细化）：歪头 + 缓慢摆动（thinkingPoseParams），
      与 confused 表情、视线上瞟叠加成完整「思考」表现 */
  thinkingPose: boolean;
  /** 身体微晃（working） */
  bodySway: boolean;
  /** 持续打字姿态（working，批次 3 I1）：双臂交替 + 低头 + 眼下视 */
  typing: boolean;
  /** 目标帧率（性能护栏，Phase 7 使用） */
  tickerFps: 15 | 30 | 60;
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

/**
 * 身体动作参数包络（M-F）：无模型自带 motion 时的内置实现。
 *
 * 调研依据：Open-LLM-VTuber 把表情/动作绑定在模型自带资源上，而 Mochi 的
 * 用户皮肤（如 Hiyori）往往没有专用动作文件——借鉴其 emotionMap 思路，
 * 用 Cubism 标准参数的时间包络实现微动作，任何 Cubism 模型都能演出
 * （driver.setParam 自动按模型实际范围钳制）。
 *
 * 优先级：皮肤清单声明的 motion/expression 实现 > 此表兜底
 * （CharacterStage 先走 resolveAction，motionGroup 为空才查此表）。
 * 返回 null = 包络已结束（one-shot 窗口内其余时间静默）。
 */
export interface BodyActionEnvelope {
  durationMs: number;
  params: (elapsedMs: number) => Record<string, number> | null;
}

/** wink（眨眨眼，M-F）：单眼闭合三角包络 + 眼角笑 + 头微偏，~700ms */
export const WINK_DURATION_MS = 700;
/** doze 包络时长（G1）：打哈欠/犯困点头 ~1600ms */
export const DOZE_DURATION_MS = 1600;
export const WINK_ENVELOPE: BodyActionEnvelope = {
  durationMs: WINK_DURATION_MS,
  params: (elapsedMs) => {
    if (elapsedMs < 0 || elapsedMs >= WINK_DURATION_MS) return null;
    const close = Math.sin((Math.PI * elapsedMs) / WINK_DURATION_MS); // 0→1→0
    return {
      ParamEyeLOpen: 1 - close,
      ParamEyeRSmile: close * 0.8,
      ParamMouthForm: 0.4 + close * 0.3,
      ParamAngleZ: close * 4,
      ParamBodyAngleZ: close * 2,
    };
  },
};

/** body 通道动作包络表（按语义动作 id 查找；wink + G1 扩容 4 项 + doze 升级） */
export const BODY_ACTION_ENVELOPES: Record<string, BodyActionEnvelope> = {
  wink: WINK_ENVELOPE,

  // ---- G1（L1 包络扩容）：均用 Cubism 标准参数，缺参数模型运行时静默跳过 ----

  /** pout（嘟嘴，G1）：嘴形收拢 + 眉微蹙 + 头微偏，~900ms */
  pout: {
    durationMs: 900,
    params: (t) => {
      if (t < 0 || t >= 900) return null;
      const f = Math.sin((Math.PI * t) / 900); // 0→1→0
      return {
        ParamMouthForm: -f,
        ParamBrowLAngle: -f * 0.35,
        ParamBrowRAngle: -f * 0.35,
        ParamAngleZ: f * -5,
        ParamBodyAngleZ: f * -2,
      };
    },
  },

  /** laugh（大笑，G1）：眼眯 + 嘴张合两拍 + 身体前后晃，~1200ms */
  laugh: {
    durationMs: 1200,
    params: (t) => {
      if (t < 0 || t >= 1200) return null;
      const fade = Math.sin((Math.PI * t) / 1200); // 整体包络 0→1→0
      const beat = Math.abs(Math.sin((2 * Math.PI * t) / 600)); // 600ms 周期两拍
      return {
        ParamEyeLSmile: fade,
        ParamEyeRSmile: fade,
        ParamMouthOpenY: beat * fade,
        ParamMouthForm: fade,
        ParamBodyAngleY: Math.sin((2 * Math.PI * t) / 600) * 2 * fade,
        ParamAngleZ: fade * 3,
      };
    },
  },

  /** shy_shake（扭捏，G1）：左右衰减摇头 + 脸颊 + 视线瞟开，~1100ms */
  shy_shake: {
    durationMs: 1100,
    params: (t) => {
      if (t < 0 || t >= 1100) return null;
      const fade = Math.exp(-2.2 * (t / 1100)); // 衰减包络
      const shake = Math.sin((2 * Math.PI * t) / 320); // ~320ms 周期左右摇
      return {
        ParamAngleX: shake * 6 * fade,
        ParamBodyAngleX: shake * 3 * fade,
        ParamCheek: Math.min(1, (t / 1100) * 2.5),
        ParamEyeBallX: shake * 0.2 * fade,
        ParamBrowLY: -0.2 * Math.min(1, (t / 1100) * 4),
        ParamBrowRY: -0.2 * Math.min(1, (t / 1100) * 4),
      };
    },
  },

  /** alert（警觉，G1）：猛抬头 + 睁眼放大 + 短促停顿后回落，~800ms */
  alert: {
    durationMs: 800,
    params: (t) => {
      if (t < 0 || t >= 800) return null;
      // 快起（前 120ms）慢落：保持段后余弦回落
      const rise = t < 120 ? t / 120 : Math.pow(1 - (t - 120) / 680, 1.6);
      return {
        ParamAngleY: rise * 12,
        ParamBodyAngleY: rise * 4,
        ParamEyeLOpen: 1 + rise * 0.3,
        ParamEyeROpen: 1 + rise * 0.3,
        ParamBrowLY: rise * 0.6,
        ParamBrowRY: rise * 0.6,
      };
    },
  },

  /** doze 升级（G1）：打哈欠/犯困点头——嘴大张 + 眼缓慢阖上再睁开 + 头下垂。
   *  之前 doze 无诚实实现（无 Doze 组直接降级 idle_neutral），现为任何模型可演 */
  doze: {
    durationMs: DOZE_DURATION_MS,
    params: (t) => {
      if (t < 0 || t >= DOZE_DURATION_MS) return null;
      const f = Math.sin((Math.PI * t) / DOZE_DURATION_MS); // 0→1→0
      const yawn = Math.pow(f, 1.4); // 哈欠主体比包络更“憋”一点
      return {
        ParamMouthOpenY: yawn,
        ParamEyeLOpen: Math.max(0, 1 - f * 1.1),
        ParamEyeROpen: Math.max(0, 1 - f * 1.1),
        ParamBrowLY: -f * 0.4,
        ParamBrowRY: -f * 0.4,
        ParamAngleY: -f * 10, // 头下垂
        ParamBodyAngleY: -f * 3,
      };
    },
  },

  // ---- 批次 3（I1，L1 包络）：均用 Cubism 标准参数，缺参数模型运行时静默跳过 ----

  /** dance（跳舞）：身体 Z 轴正弦摇摆两拍 + 头部反相随动 + 节拍路脚微蹲 + 笑脸，~2.4s */
  dance: {
    durationMs: 2400,
    params: (t) => {
      if (t < 0 || t >= 2400) return null;
      const sway = Math.sin((2 * Math.PI * t) / 1200); // 1.2s 一个左右摆周期，共两拍
      const beat = Math.abs(Math.sin((Math.PI * t) / 600)); // 600ms 节拍，用于路脚微蹲与眨眼
      const fade = Math.min(1, t / 300, (2400 - t) / 300); // 首尾 300ms 淡入淡出
      return {
        ParamBodyAngleZ: sway * 8 * fade,
        ParamAngleZ: -sway * 10 * fade,
        ParamBodyAngleY: -beat * 2 * fade,
        ParamMouthForm: 0.5 * fade,
        ParamEyeRSmile: 0.5 * fade,
        ParamEyeLSmile: 0.5 * fade,
      };
    },
  },

  /** finger_heart（比心）：举手定格 + 头微偏 + 笑眼笑嘴；Hiyori 类模型无手指参数，
   *  用「手臂 + 表情组合」表意（手势级演出走 L3 资产），~1.6s */
  finger_heart: {
    durationMs: 1600,
    params: (t) => {
      if (t < 0 || t >= 1600) return null;
      // 前 300ms 快举手，尾 300ms 收回，中段定格
      const raise = t < 300 ? t / 300 : t >= 1300 ? (1600 - t) / 300 : 1;
      return {
        ParamArmLA: 2 * raise,
        ParamAngleZ: 6 * raise,
        ParamBodyAngleZ: 2 * raise,
        ParamEyeLOpen: 1 - 0.6 * raise, // 笑眼（弯成月牙）
        ParamEyeROpen: 1 - 0.6 * raise,
        ParamEyeLSmile: 0.8 * raise,
        ParamEyeRSmile: 0.8 * raise,
        ParamMouthForm: 0.8 * raise,
      };
    },
  },

  /** blow_kiss（飞吻）：抬手到脸侧 + 嘟嘴蓄力 → 张手送出 + 身体前倾 → 眨眼收尾，~1.6s */
  blow_kiss: {
    durationMs: 1600,
    params: (t) => {
      if (t < 0 || t >= 1600) return null;
      // 阶段：0–400 抬手蓄力；400–700 嘟嘴；700–1000 张手送出；1000–1600 回收+眨眼
      const raise =
        t < 400 ? (t / 400) * 1.6 : t >= 1300 ? Math.max(0, (1600 - t) / 300) * 1.6 : 1.6;
      const pucker = t >= 400 && t < 700 ? 1 : 0;
      const blow = t >= 700 && t < 1000 ? (t - 700) / 300 : 0;
      const wink = t >= 1000 && t < 1300 ? Math.sin((Math.PI * (t - 1000)) / 300) : 0;
      return {
        ParamArmLA: raise,
        ParamMouthForm: pucker ? -0.8 : blow ? 0.5 : 0,
        ParamMouthOpenY: blow * 0.6,
        ParamBodyAngleY: blow * -2,
        ParamAngleZ: raise * 3,
        ParamEyeROpen: 1 - wink,
      };
    },
  },

  /** question（满脸问号）：歪头停顿 + 双眉不对称 + 眼神游移 + 身体微缩，~1.8s。
   *  问号贴图属容器渲染层（I3），包络层用纯姿态表意 */
  question: {
    durationMs: 1800,
    params: (t) => {
      if (t < 0 || t >= 1800) return null;
      // 歪头：300ms 歪到位，停到 1200ms，600ms 回正
      const tilt = t < 300 ? t / 300 : t >= 1200 ? Math.max(0, (1800 - t) / 600) : 1;
      const wander = t < 900 ? -0.6 : 0.5; // 眼神先左后右游移
      return {
        ParamAngleZ: -12 * tilt,
        ParamBrowLForm: 0.6 * tilt,
        ParamBrowRForm: -0.6 * tilt,
        ParamBrowLY: tilt * 0.3,
        ParamBrowRY: -tilt * 0.3,
        ParamEyeBallX: wander * tilt,
        ParamBodyAngleZ: -3 * tilt,
      };
    },
  },

  /** idle_hum（哼歌摇头，批次 3 I2）：内部动作（不在语义词表），闲置轮换池专用。
   *  头部节拍小晃 + 嘴形哼唱开合 + 眼睛微眯，~2.4s */
  idle_hum: {
    durationMs: 2400,
    params: (t) => {
      if (t < 0 || t >= 2400) return null;
      const fade = Math.min(1, t / 300, (2400 - t) / 300);
      const sway = Math.sin((2 * Math.PI * t) / 600); // 600ms 一个小晃周期
      const hum = Math.sin((2 * Math.PI * t) / 1200); // 1.2s 一个哼唱开合
      return {
        ParamAngleZ: sway * 3 * fade,
        ParamBodyAngleZ: sway * 1.5 * fade,
        ParamMouthOpenY: Math.max(0, hum) * 0.25 * fade,
        ParamMouthForm: 0.3 * fade,
        ParamEyeLSmile: 0.4 * fade,
        ParamEyeRSmile: 0.4 * fade,
      };
    },
  },

  /** type（打字，oneshot 窗口 2.4s；working 状态的持续打字由 driver typing 位驱动） */
  type: {
    durationMs: 2400,
    params: (t) => {
      if (t < 0 || t >= 2400) return null;
      const fade = Math.min(1, t / 200, (2400 - t) / 200);
      const cycle = (2 * Math.PI * t) / 150;
      return {
        ParamArmLA: (0.35 + 0.15 * Math.sin(cycle)) * fade,
        ParamArmRA: (0.35 + 0.15 * Math.sin(cycle + Math.PI)) * fade, // 双臂反相交替
        ParamAngleY: -6 * fade,
        ParamEyeBallY: -0.4 * fade,
        ParamBodyAngleY: -2 * fade,
      };
    },
  },
};

/**
 * 反射专用表情预设（M-B）：非语义词表/情绪枚举的本地表情。
 * worried（担忧）：眉心微蹙 + 嘴角下垂 + 头部微偏——工具失败时的关切表情，
 * 与 sad（明显低落）区分。face 通道查找顺序：EMOTION_PRESETS → 此表。
 */
export const FACE_REFLEX_PRESETS: Record<string, Record<string, number>> = {
  worried: {
    ParamBrowLY: 0.4,
    ParamBrowRY: 0.4,
    ParamBrowLAngle: -0.4,
    ParamBrowRAngle: -0.4,
    ParamMouthForm: -0.5,
    ParamAngleZ: -2,
  },
};

/** 思考姿态参数（纯函数，便于 vitest 覆盖）：歪头 + 缓慢头部摆动 +
 *  身体微倾。数值为 Hiyori 实际参数单位（角度），驱动层按模型范围
 *  钳制；nowSec 为秒级时钟，驱动缓慢摆动（周期 ~5.7s）。
 *  与视线上瞟（gazeOffsetY>0）叠加：低头沉思 + 眼睛上瞟。 */
export function thinkingPoseParams(nowSec: number): Record<string, number> {
  const sway = Math.sin(nowSec * 1.1);
  return {
    ParamAngleZ: 14 + sway * 5,
    ParamAngleY: -6,
    ParamBodyAngleZ: 5,
  };
}

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
  thinkingPose: boolean;
  bodySway: boolean;
  typing: boolean;
  tickerFps: 15 | 30 | 60;
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
    thinkingPose: false,
    bodySway: false,
    typing: false,
    tickerFps: 30,
  },
  talking: {
    motionPreference: ["Idle"],
    motionPriority: "normal",
    eyesClosed: false,
    mouthEnabled: true,
    gazeEnabled: true,
    gazeOffsetY: 0,
    thinkingPose: false,
    bodySway: false,
    typing: false,
    tickerFps: 60,
  },
  thinking: {
    motionPreference: ["Think", "Idle"],
    motionPriority: "normal",
    forcedEmotion: "confused",
    eyesClosed: false,
    mouthEnabled: false,
    gazeEnabled: true,
    gazeOffsetY: 0.4,
    thinkingPose: true,
    bodySway: false,
    typing: false,
    tickerFps: 60,
  },
  working: {
    motionPreference: ["Idle"],
    motionPriority: "normal",
    eyesClosed: false,
    mouthEnabled: false,
    gazeEnabled: true,
    gazeOffsetY: 0,
    thinkingPose: false,
    bodySway: false,
    typing: true, // 批次 3 I1：工作中持续打字演出（双臂交替 + 低头）
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
    thinkingPose: false,
    bodySway: false,
    typing: false,
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
    thinkingPose: false,
    bodySway: false,
    typing: false,
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
    thinkingPose: rule.thinkingPose,
    bodySway: rule.bodySway,
    typing: rule.typing,
    tickerFps: rule.tickerFps,
  };
}

/** Hiyori PRO t11 实际能力档案（加载时可与运行时 dump 结果核对） */
export const HIYORI_PROFILE: ModelProfile = {
  motionGroups: ["Idle", "Flick", "FlickDown", "FlickUp", "Tap", "Tap@Body", "Flick@Body"],
  expressions: [],
};
