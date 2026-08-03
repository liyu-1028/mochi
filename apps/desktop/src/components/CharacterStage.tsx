/**
 * CharacterStage —— Live2D 角色渲染层（M0-S3，功能清单 2.1/2.2）。
 *
 * 加载成功：透明画布渲染模型，状态机把 (characterState, emotion) 实时
 * 翻译为动作/表情/参数；加载失败（Core 缺失/模型 404/解析错）降级回
 * CharacterBadge，对话功能不受影响（ADR-0003 D2）。
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
import { HIYORI_PROFILE, resolveAnimation } from "../live2d/stateMachine";

export function CharacterStage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<StageHandle | null>(null);
  const driverRef = useRef<CharacterDriver | null>(null);
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);

  const characterState = useConversation((s) => s.characterState);
  const emotion = useConversation((s) => s.emotion);

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

  // 状态机：(状态, 情绪) → 动画计划。Phase 6 的口型/视线在此之上叠加覆写
  useEffect(() => {
    const driver = driverRef.current;
    if (!driver || !ready) return;
    driver.applyPlan(resolveAnimation(characterState, emotion, HIYORI_PROFILE));
  }, [characterState, emotion, ready]);

  if (failed) return <CharacterBadge />;
  return <div className="character-stage" ref={containerRef} />;
}
