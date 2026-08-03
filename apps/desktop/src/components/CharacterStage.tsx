/**
 * CharacterStage —— Live2D 角色渲染层（M0-S3，功能清单 2.1）。
 *
 * 加载成功：透明画布渲染模型（后续 Phase 在此挂状态机/口型/视线驱动）；
 * 加载失败（Core 缺失/模型 404/解析错）：降级回 CharacterBadge，
 * 对话功能不受影响（ADR-0003 D2）。
 */
import { useEffect, useRef, useState } from "react";
import { CharacterBadge } from "./CharacterBadge";
import {
  DEFAULT_MODEL_URL,
  disposeStage,
  loadCharacterStage,
  type StageHandle,
} from "../live2d/core";

export function CharacterStage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let stage: StageHandle | null = null;
    let cancelled = false;

    loadCharacterStage(container, DEFAULT_MODEL_URL)
      .then((loaded) => {
        // StrictMode 双挂载：卸载后才完成的加载立即销毁
        if (cancelled) {
          disposeStage(loaded);
        } else {
          stage = loaded;
        }
      })
      .catch((err) => {
        console.error("[CharacterStage] Live2D 加载失败，降级为占位形象：", err);
        if (!cancelled) setFailed(true);
      });

    return () => {
      cancelled = true;
      if (stage) disposeStage(stage);
    };
  }, []);

  if (failed) return <CharacterBadge />;
  return <div className="character-stage" ref={containerRef} />;
}
