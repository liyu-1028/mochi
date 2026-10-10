/**
 * 声明式参数包络解释器（skin.json v3，G3）。
 *
 * 把 skin manifest 里的 paramEnvelope 声明编译成逐帧求值函数：
 * 输入动作经过时间（ms），输出 { paramId: value } 快照。与内置
 * BODY_ACTION_ENVELOPES（stateMachine.ts）同形，CharacterStage 帧循环
 * 无差别消费；skin 声明了包络时优先于内置兜底。
 *
 * 防御性约定：manifest 由服务端强校验，但前端不信任运行时数据——
 * 畸形声明（点数不足/时间戳不递增/空 keyframes）编译返回 null，
 * 调用方回落内置包络链，绝不抛异常打断渲染循环。
 */

import type { ParamEnvelopeBinding } from "../../api/skinsClient";

export interface EnvelopeDeclaration {
  durationMs: number;
  easing?: "linear" | "smoothstep";
  keyframes: readonly {
    param: string;
    points: readonly (readonly [number, number])[];
  }[];
}

/** 编译产物：与内置 BodyActionEnvelope 同形（durationMs + params(t)）。 */
export interface CompiledParamEnvelope {
  durationMs: number;
  /** elapsedMs → { paramId: value }；越界时间钳制到首末点（自然保持端点值）。 */
  params: (elapsedMs: number) => Record<string, number>;
}

function smoothstep(fraction: number): number {
  return fraction * fraction * (3 - 2 * fraction);
}

/** 单参数点列在 t 处的线性/平滑插值值（调用方保证点列合法）。 */
function interpolate(
  points: readonly (readonly [number, number])[],
  t: number,
  eased: boolean,
): number {
  const clamped = Math.min(Math.max(t, points[0][0]), points[points.length - 1][0]);
  for (let i = 1; i < points.length; i += 1) {
    const [t1, v1] = points[i];
    if (clamped <= t1) {
      const [t0, v0] = points[i - 1];
      const span = t1 - t0;
      if (span <= 0) return v1;
      let fraction = (clamped - t0) / span;
      if (eased) fraction = smoothstep(fraction);
      return v0 + (v1 - v0) * fraction;
    }
  }
  return points[points.length - 1][1];
}

/** 编译声明式包络；畸形声明返回 null（调用方回落内置兜底）。 */
export function compileParamEnvelope(
  decl: ParamEnvelopeBinding | EnvelopeDeclaration | null | undefined,
): CompiledParamEnvelope | null {
  if (!decl || typeof decl.durationMs !== "number" || decl.durationMs <= 0) return null;
  if (!Array.isArray(decl.keyframes) || decl.keyframes.length === 0) return null;

  const tracks: {
    param: string;
    points: readonly (readonly [number, number])[];
  }[] = [];
  for (const keyframe of decl.keyframes) {
    if (!keyframe || typeof keyframe.param !== "string" || keyframe.param.length === 0) {
      return null;
    }
    const points = keyframe.points;
    if (!Array.isArray(points) || points.length < 2) return null;
    let prevT = -1;
    for (const point of points) {
      if (!Array.isArray(point) || point.length !== 2) return null;
      const [t, v] = point;
      if (typeof t !== "number" || typeof v !== "number") return null;
      if (!Number.isFinite(t) || !Number.isFinite(v)) return null;
      if (t <= prevT) return null; // 必须严格递增
      prevT = t;
    }
    if (points[0][0] !== 0) return null;
    tracks.push({ param: keyframe.param, points });
  }

  const eased = decl.easing === "smoothstep";
  return {
    durationMs: decl.durationMs,
    params: (elapsedMs: number) => {
      const snapshot: Record<string, number> = {};
      for (const track of tracks) {
        snapshot[track.param] = interpolate(track.points, elapsedMs, eased);
      }
      return snapshot;
    },
  };
}
