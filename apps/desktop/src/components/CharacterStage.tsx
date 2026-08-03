/**
 * CharacterStage —— Live2D 角色渲染层（M0-S3，功能清单 2.1/2.2/2.3/2.4）。
 *
 * 加载成功：透明画布渲染模型，状态机把 (characterState, emotion) 实时
 * 翻译为动作/表情/参数；text.delta 驱动口型；光标驱动视线。
 * 加载失败（Core 缺失/模型 404/解析错）降级回 CharacterBadge，
 * 对话功能不受影响（ADR-0003 D2）。
 */
import { useEffect, useRef, useState } from "react";
import { CharacterBadge } from "./CharacterBadge";
import { useConversation } from "../store/conversation";
import {
  DEFAULT_MODEL_URL,
  disposeStage,
  loadCharacterStage,
  type StageHandle,
} from "../live2d/core";
import { createDriver, type CharacterDriver } from "../live2d/driver";
import { lerpGaze, normalizeGaze, type GazeTarget } from "../live2d/gaze";
import { MOUTH_CLOSED, onDelta, stepMouth, type MouthState } from "../live2d/mouth";
import { HIYORI_PROFILE, resolveAnimation, type AnimationPlan } from "../live2d/stateMachine";

export function CharacterStage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<StageHandle | null>(null);
  const driverRef = useRef<CharacterDriver | null>(null);
  const planRef = useRef<AnimationPlan | null>(null);
  const mouthRef = useRef<MouthState>(MOUTH_CLOSED);
  const gazeTargetRef = useRef<GazeTarget>({ x: 0, y: 0 });
  const gazeCurrentRef = useRef<GazeTarget>({ x: 0, y: 0 });
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);

  const characterState = useConversation((s) => s.characterState);
  const emotion = useConversation((s) => s.emotion);
  const lastTextDeltaAt = useConversation((s) => s.lastTextDeltaAt);
  const lastTextDelta = useConversation((s) => s.lastTextDelta);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let cancelled = false;

    loadCharacterStage(container, DEFAULT_MODEL_URL)
      .then((loaded) => {
        // StrictMode 双挂载：卸载后才完成的加载立即销毁
        if (cancelled) {
          disposeStage(loaded);
          return;
        }
        stageRef.current = loaded;
        driverRef.current = createDriver(loaded);
        setReady(true);
      })
      .catch((err) => {
        console.error("[CharacterStage] Live2D 加载失败，降级为占位形象：", err);
        if (!cancelled) setFailed(true);
      });

    return () => {
      cancelled = true;
      driverRef.current?.dispose();
      driverRef.current = null;
      if (stageRef.current) disposeStage(stageRef.current);
      stageRef.current = null;
    };
  }, []);

  // 状态机：(状态, 情绪) → 动画计划
  useEffect(() => {
    const driver = driverRef.current;
    if (!driver || !ready) return;
    const plan = resolveAnimation(characterState, emotion, HIYORI_PROFILE);
    planRef.current = plan;
    driver.applyPlan(plan);
  }, [characterState, emotion, ready]);

  // 口型（2.3）：每个 text.delta 触发一次张嘴；帧覆写负责衰减与闭合
  useEffect(() => {
    if (lastTextDeltaAt > 0) {
      mouthRef.current = onDelta(mouthRef.current, lastTextDelta);
    }
  }, [lastTextDeltaAt, lastTextDelta]);

  // 视线（2.4）：光标位置 → 归一化目标；帧覆写 lerp 逼近
  useEffect(() => {
    const container = containerRef.current;
    if (!ready || !container) return;
    const onMove = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      gazeTargetRef.current = normalizeGaze(e.clientX, e.clientY, rect);
    };
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [ready]);

  // 每帧参数覆写：口型开合 + 眼球目标（含思考上瞟偏移）
  useEffect(() => {
    const driver = driverRef.current;
    if (!ready || !driver) return;
    let lastNow: number | null = null;
    return driver.addFrameOverride((_params, now) => {
      const deltaMs = lastNow === null ? 16 : Math.min(100, (now - lastNow) * 1000);
      lastNow = now;
      const plan = planRef.current;

      // 口型：非说话期也继续衰减，保证平滑闭合
      mouthRef.current = stepMouth(mouthRef.current, deltaMs);
      if (mouthRef.current.open > 0) {
        driver.setParam("ParamMouthOpenY", mouthRef.current.open);
      }

      // 视线：sleeping/error 状态由状态机禁用
      if (plan?.gazeEnabled) {
        gazeCurrentRef.current = lerpGaze(gazeCurrentRef.current, gazeTargetRef.current);
        driver.setParam("ParamEyeBallX", gazeCurrentRef.current.x);
        driver.setParam("ParamEyeBallY", gazeCurrentRef.current.y + plan.gazeOffsetY);
      }
    });
  }, [ready]);

  if (failed) return <CharacterBadge />;
  return <div className="character-stage" ref={containerRef} />;
}
