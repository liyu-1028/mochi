/**
 * locomotion —— 容器联动位置指令的纯函数事实源（I3/M-H）。
 *
 * 窗口扩为「角色活动区」：宽度 = 角色宽 × LOCOMOTION_AREA_RATIO（左右各留
 * 约半个身位的余量），角色默认居中；locomotion cue 把角色在余量区内平移/
 * 缩放（CSS transform），并叠加姿态参数。
 *
 * 位置是持久状态（非 one-shot）：进入非 idle 状态或超时 LOCOMOTION_STAY_MS
 * 自动回位（内部 null 状态）。模型可演性无皮肤依赖——纯布局 + 标准参数，
 * 缺参由 driver 静默跳过（与包络同口径）。
 */
import type { LocomotionActionId } from "@mochi/protocol";

/** 非回位位置的停留时长：超时自动回位（说话/思考立即回位另行守卫）。 */
export const LOCOMOTION_STAY_MS = 14_000;

/** 活动区宽度 = 角色显示宽 × 该比例（含左右余量各约 0.6 个身位）。 */
export const LOCOMOTION_AREA_RATIO = 2.2;

/** 位移/姿态目标（逻辑 px 与 Live2D 参数值）。 */
export interface LocomotionPose {
  /** 水平位移（px，右为正） */
  dx: number;
  /** 垂直位移（px，下为正） */
  dy: number;
  /** 整体缩放（1 = 原大） */
  scale: number;
  /** ParamBodyAngleZ 目标（倚靠倾斜） */
  bodyZ: number;
  /** ParamAngleZ 目标（头部倾斜） */
  headZ: number;
  /** ParamBodyAngleY 目标（前倾/后仰） */
  bodyY: number;
  /** ParamAngleY 目标（低头） */
  headY: number;
}

const REST_POSE: LocomotionPose = {
  dx: 0,
  dy: 0,
  scale: 1,
  bodyZ: 0,
  headZ: 0,
  bodyY: 0,
  headY: 0,
};

type LocomotionPoseResolver = (
  containerW: number,
  containerH: number,
  aspect: number,
) => LocomotionPose;

/** 当前不注册位置指令；后续动作仍通过同一入口解析位移/姿态目标。 */
const POSE_RESOLVERS: ReadonlyMap<LocomotionActionId, LocomotionPoseResolver> = new Map<
  LocomotionActionId,
  LocomotionPoseResolver
>();

/**
 * 位置 → 位移/姿态目标。
 *
 * @param containerW 活动区（舞台容器）宽
 * @param containerH 舞台容器高 ≈ 角色显示高
 * @param aspect     模型原始宽高比（modelWidth / modelHeight）
 * @returns 位移与姿态目标；null 或未注册的位置返回中性姿态
 */
export function locomotionPose(
  id: LocomotionActionId | null,
  containerW: number,
  containerH: number,
  aspect: number,
): LocomotionPose {
  const resolve = id === null ? undefined : POSE_RESOLVERS.get(id);
  return resolve?.(containerW, containerH, aspect) ?? REST_POSE;
}

/** 姿态向目标逐帧靠近（帧覆写用）：简单指数趋近，步长随距离衰减。 */
export function approachLerp(current: number, target: number, factor = 0.12): number {
  const next = current + (target - current) * factor;
  return Math.abs(target - next) < 0.01 ? target : next;
}

/** CSS transform 字符串（.character-stage 容器用；transition 在样式层）。 */
export function locomotionTransform(pose: LocomotionPose): string {
  return `translate(${pose.dx.toFixed(1)}px, ${pose.dy.toFixed(1)}px) scale(${pose.scale})`;
}
