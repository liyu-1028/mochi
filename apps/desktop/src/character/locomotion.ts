/**
 * locomotion —— 容器联动位置指令的纯函数事实源（I3/M-H）。
 *
 * 窗口扩为「角色活动区」：宽度 = 角色宽 × LOCOMOTION_AREA_RATIO（左右各留
 * 约半个身位的余量），角色默认居中；locomotion cue 把角色在余量区内平移/
 * 缩放（CSS transform，容器边缘即「墙」），并叠加倚靠/趴伏姿态参数。
 *
 * 位置是持久状态（非 one-shot）：进入非 idle 状态或超时 LOCOMOTION_STAY_MS
 * 自动回位（come_back）。模型可演性无皮肤依赖——纯布局 + 标准参数，
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

/**
 * 位置 → 位移/姿态目标。
 *
 * @param containerW 活动区（舞台容器）宽
 * @param containerH 舞台容器高 ≈ 角色显示高
 * @param aspect     模型原始宽高比（modelWidth / modelHeight）
 * @returns 位移与姿态目标；未知位置等同 come_back（防御）
 */
export function locomotionPose(
  id: LocomotionActionId,
  containerW: number,
  containerH: number,
  aspect: number,
): LocomotionPose {
  const charW = containerH * aspect;
  // 角色可平移的横向余量（每侧）：活动区宽超出角色宽的部分
  const margin = Math.max(0, (containerW - charW) / 2);
  if (margin <= 0) return REST_POSE; // 窗口未扩容（窄角色/兜底布局）：不动
  switch (id) {
    case "lean_edge":
      // 靠墙（容器右边缘）：贴边 + 身体向墙倾斜
      return { ...REST_POSE, dx: margin - 2, bodyZ: 6, headZ: 4 };
    case "peek_out":
      // 探头（左边缘）：半个身子移出窗外（窗口外不可见 → 只探出半身）
      return { ...REST_POSE, dx: -(margin + charW * 0.45), bodyZ: -4 };
    case "peek_dock":
      // 趴输入框（底部 dock 上方）：下移压近 + 前倾低头
      return { ...REST_POSE, dy: 30, scale: 1.04, bodyY: -5, headY: -8 };
    case "lean_bubble":
      // 靠气泡（头部侧上方）：轻微上提侧靠，头偏向气泡侧
      return { ...REST_POSE, dy: -10, dx: -24, headZ: -6 };
    case "come_back":
    default:
      return REST_POSE;
  }
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
