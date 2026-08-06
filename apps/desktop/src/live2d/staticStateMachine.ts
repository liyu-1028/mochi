/**
 * 静态皮肤状态机（M1-S1）：(状态, 情绪, 皮肤清单) → StaticAnimationPlan。
 *
 * 与 live2d/stateMachine 同层的纯函数：动画开关取自 skin.json 的
 * ``animation`` 逐状态表（缺省全关），情绪表达取 ``emotionMapping`` 微缩放。
 */
import type { CharacterState, Emotion } from "@mochi/protocol";
import type { SkinManifest } from "../api/skinsClient";
import type { StaticAnimationPlan } from "./staticDriver";

export type StaticSkinInput = Pick<SkinManifest, "animation" | "emotionMapping">;

export function resolveStaticAnimation(
  state: CharacterState,
  emotion: Emotion | null,
  skin: StaticSkinInput,
): StaticAnimationPlan {
  const stateAnim = skin.animation?.[state];
  const effect = skin.emotionMapping?.[emotion ?? "neutral"];
  return {
    float: stateAnim?.float ?? false,
    breathe: stateAnim?.breathe ?? false,
    sway: stateAnim?.sway ?? false,
    talking: state === "talking",
    sleeping: state === "sleeping",
    error: state === "error",
    emotionScale: effect?.scale ?? 1,
  };
}
