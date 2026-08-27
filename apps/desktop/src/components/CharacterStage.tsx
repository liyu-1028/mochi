/**
 * CharacterStage —— 角色渲染层（M0-S3 起，M1-S1 皮肤双路径）。
 *
 * 皮肤驱动（3.2/3.3/3.4）：resourceType=live2d 走 Cubism 模型；
 * static 走 PIXI Sprite + 正弦动画（staticDriver）。能力档案来自
 * skin.json capabilities（HIYORI_PROFILE 硬编码已消除）。
 *
 * 加载成功：透明画布渲染，状态机把 (characterState, emotion) 实时翻译为
 * 动作/表情/参数（live2d）或 sprite 变换（static）；text.delta 驱动口型、
 * 光标驱动视线（均仅 live2d）。加载失败降级回 CharacterBadge（ADR-0003 D2）。
 *
 * 换肤不闪白（ADR-0006 D10）：新舞台加载完成后才 dispose 旧舞台。
 */
import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { resolveSkinId, type SkinSummary } from "../api/skinsClient";
import { useConversation } from "../store/conversation";
import { CharacterBadge } from "./CharacterBadge";
import { disposeStage, loadCharacterStage, type StageHandle } from "../live2d/core";
import { createDriver, type CharacterDriver } from "../live2d/driver";
import { lerpGaze, normalizeGaze, type GazeTarget } from "../live2d/gaze";
import { MOUTH_CLOSED, onDelta, stepMouth, volumeToOpen, type MouthState } from "../live2d/mouth";
import { ttsPlayer } from "../live2d/ttsPlayer";
import { useTTSState } from "../hooks/useTTS";
import { MAX_STATIC_UPSCALE } from "../layout/characterLayout";
import { disposeStaticStage, loadStaticStage, type StaticStageHandle } from "../live2d/staticCore";
import { createStaticDriver, type StaticDriver } from "../live2d/staticDriver";
import { resolveStaticAnimation } from "../live2d/staticStateMachine";
import { resolveAnimation, type AnimationPlan, type ModelProfile } from "../live2d/stateMachine";
import {
  createSampleWindow,
  decorationsPaused,
  effectiveFps,
  nextFpsLevel,
  type FpsLevel,
} from "../live2d/powerGuard";
import { useSettings } from "../store/settings";

type AnyStage = StageHandle | StaticStageHandle;
type AnyDriver = CharacterDriver | StaticDriver;

function disposeAnyStage(stage: AnyStage): void {
  if ("model" in stage) disposeStage(stage);
  else disposeStaticStage(stage);
}

/** 皮肤清单 → Live2D 能力档案（模型实际拥有的动作组/表情，状态机据此挑选）。 */
export function profileForSkin(skin: SkinSummary): ModelProfile {
  return {
    motionGroups: skin.capabilities?.motionGroups ?? [],
    expressions: skin.capabilities?.expressions ?? [],
  };
}

interface CharacterStageProps {
  /** 当前皮肤（null = 尚未就绪，不加载）；id 变化触发重建（3.3 热切换）。 */
  skin: SkinSummary | null;
  /** 左键点击角色时触发（唤起输入框，open 状态由 App 持有） */
  onActivate?: () => void;
  /** 右键角色时触发（弹出上下文菜单），回传光标视口坐标供定位 */
  onContextMenu?: (x: number, y: number) => void;
  /** 模型加载完成：回传原始尺寸，App 据此推导窗口布局（布局倒置）；
   *  maxUpscale 仅静态皮肤传（渲染放大上限，窗口与 capped 角色严格一致） */
  onModelReady?: (modelWidth: number, modelHeight: number, maxUpscale?: number) => void;
  /** 加载失败降级为占位形象：App 回到兜底布局 */
  onFallback?: () => void;
}

export function CharacterStage({
  skin,
  onActivate,
  onContextMenu,
  onModelReady,
  onFallback,
}: CharacterStageProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<AnyStage | null>(null);
  /** 换肤期间暂存的旧舞台：新舞台就绪后才销毁，避免闪白。 */
  const previousStageRef = useRef<AnyStage | null>(null);
  const driverRef = useRef<AnyDriver | null>(null);
  const planRef = useRef<AnimationPlan | null>(null);
  const mouthRef = useRef<MouthState>(MOUTH_CLOSED);
  const gazeTargetRef = useRef<GazeTarget>({ x: 0, y: 0 });
  const gazeCurrentRef = useRef<GazeTarget>({ x: 0, y: 0 });
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);
  // 性能护栏（2.6）：当前降档档位 + 计划重放回调（档位变化时重打掩码）
  const powerLevelRef = useRef<FpsLevel>(0);
  const reapplyPlanRef = useRef<() => void>(() => {});

  const characterState = useConversation((s) => s.characterState);
  // 播报期服务端已 idle（text.end 即回落）：前端取有效态保持 talking（M1-S2）
  const ttsPlaying = useTTSState((s) => s.playing);
  const effectiveState = ttsPlaying ? "talking" : characterState;
  const emotion = useConversation((s) => s.emotion);
  const lastTextDeltaAt = useConversation((s) => s.lastTextDeltaAt);
  const lastTextDelta = useConversation((s) => s.lastTextDelta);
  // 省电模式（2.6）：钉最低档 + 暂停装饰动画；事实源 sidecar，跨窗口同步
  const powerSave = useSettings((s) => s.powerSave);

  const isLive2D = skin?.resourceType === "live2d";

  // 皮肤加载：id 变化 → cleanup 暂存旧舞台 → 新加载就绪后销毁旧的
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !skin) return;
    let cancelled = false;

    const live2d = skin.resourceType === "live2d";
    const url = live2d
      ? `${skin.resourceBaseUrl}/${skin.modelFile ?? ""}`
      : `${skin.resourceBaseUrl}/${skin.imageFile ?? "avatar.png"}`;
    const loading = live2d ? loadCharacterStage(container, url) : loadStaticStage(container, url);

    loading
      .then((loaded) => {
        // StrictMode 双挂载：卸载后才完成的加载立即销毁
        if (cancelled) {
          disposeAnyStage(loaded);
          return;
        }
        stageRef.current = loaded;
        driverRef.current = live2d
          ? createDriver(loaded as StageHandle)
          : createStaticDriver(loaded as StaticStageHandle);
        // 新舞台就绪才销毁旧舞台：换肤全程有画面（ADR-0006 D10）
        if (previousStageRef.current) {
          disposeAnyStage(previousStageRef.current);
          previousStageRef.current = null;
        }
        // 启动里程碑打点（performance.now 相对页面 timeOrigin）：
        // 1.1 冷启动验收 / 2.6 性能回归排查用，release 下经 macOS 统一日志可见
        console.info(
          `[mochi] character-ready(${skin.resourceType}) +${Math.round(performance.now())}ms`,
        );
        onModelReady?.(
          loaded.modelWidth,
          loaded.modelHeight,
          live2d ? undefined : MAX_STATIC_UPSCALE,
        );
        setReady(true);
      })
      .catch((err) => {
        console.error("[CharacterStage] 皮肤加载失败，降级为占位形象：", err);
        if (!cancelled) {
          setFailed(true);
          onFallback?.();
        }
      });

    return () => {
      cancelled = true;
      driverRef.current?.dispose();
      driverRef.current = null;
      setReady(false);
      // 旧画布留给新加载就绪时销毁；彻底卸载由下方 unmount effect 收口
      if (stageRef.current) previousStageRef.current = stageRef.current;
      stageRef.current = null;
    };
  }, [
    skin?.id,
    skin?.resourceType,
    skin?.resourceBaseUrl,
    skin?.modelFile,
    skin?.imageFile,
    onModelReady,
    onFallback,
  ]);

  // 彻底卸载：残留舞台一并销毁
  useEffect(
    () => () => {
      if (stageRef.current) disposeAnyStage(stageRef.current);
      if (previousStageRef.current) disposeAnyStage(previousStageRef.current);
      stageRef.current = null;
      previousStageRef.current = null;
    },
    [],
  );

  // 状态机：(有效状态, 情绪) → 动画计划（双路径）；
  // 性能护栏（2.6）掩码：降档后改写 tickerFps + 关装饰动画，档位变化时重放。
  useEffect(() => {
    const driver = driverRef.current;
    if (!driver || !ready || !skin) return;
    const applyGuarded = () => {
      const level = powerLevelRef.current;
      if (driver.kind === "live2d") {
        const raw = resolveAnimation(effectiveState, emotion, profileForSkin(skin));
        const plan: AnimationPlan = {
          ...raw,
          tickerFps: effectiveFps(raw.tickerFps, level) as AnimationPlan["tickerFps"],
          bodySway: raw.bodySway && !decorationsPaused(level),
        };
        planRef.current = plan;
        driver.applyPlan(plan);
      } else {
        const raw = resolveStaticAnimation(effectiveState, emotion, skin);
        const paused = decorationsPaused(level);
        driver.applyPlan({
          ...raw,
          float: raw.float && !paused,
          breathe: raw.breathe && !paused,
          sway: raw.sway && !paused,
        });
      }
    };
    reapplyPlanRef.current = applyGuarded;
    applyGuarded();
  }, [effectiveState, emotion, ready, skin]);

  // 性能护栏主循环（2.6）：逐帧采样帧耗时，每秒用近 5s 均值决策降/升档；
  // 省电模式钉最低档。对话链路（WS）与渲染解耦，降档不影响功能。
  useEffect(() => {
    const stage = stageRef.current;
    if (!ready || !stage) return;
    const sampleWindow = createSampleWindow();
    const sample = () => sampleWindow.push(stage.app.ticker.deltaMS, performance.now());
    stage.app.ticker.add(sample);

    const evaluate = () => {
      const next = nextFpsLevel(powerLevelRef.current, sampleWindow.average(), powerSave);
      if (next === powerLevelRef.current) return;
      powerLevelRef.current = next;
      stage.app.ticker.maxFPS = effectiveFps(
        driverRef.current?.kind === "live2d" ? (planRef.current?.tickerFps ?? 60) : 60,
        next,
      );
      reapplyPlanRef.current();
    };
    evaluate(); // 省电开关切换时立即生效
    const timer = window.setInterval(evaluate, 1000);
    return () => {
      stage.app.ticker.remove(sample);
      window.clearInterval(timer);
    };
  }, [ready, powerSave]);

  // 口型（2.3，仅 live2d）：每个 text.delta 触发一次张嘴；帧覆写负责衰减与闭合
  useEffect(() => {
    if (!isLive2D) return;
    if (lastTextDeltaAt > 0) {
      mouthRef.current = onDelta(mouthRef.current, lastTextDelta);
    }
  }, [isLive2D, lastTextDeltaAt, lastTextDelta]);

  // 视线（2.4，仅 live2d）：光标位置 → 归一化目标；帧覆写 lerp 逼近
  useEffect(() => {
    const container = containerRef.current;
    if (!ready || !container || !isLive2D) return;
    const onMove = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      gazeTargetRef.current = normalizeGaze(e.clientX, e.clientY, rect);
    };
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [ready, isLive2D]);

  // 每帧参数覆写（仅 live2d）：口型开合 + 眼球目标（含思考上瞟偏移）
  useEffect(() => {
    const driver = driverRef.current;
    if (!ready || !driver || driver.kind !== "live2d") return;
    let lastNow: number | null = null;
    return driver.addFrameOverride((_params, now) => {
      const deltaMs = lastNow === null ? 16 : Math.min(100, (now - lastNow) * 1000);
      lastNow = now;
      const plan = planRef.current;

      // 口型：播报期音量驱动（2.7），否则 delta 节奏 + 平滑衰减
      if (ttsPlaying) {
        const open = volumeToOpen(ttsPlayer.level());
        if (open > 0) driver.setParam("ParamMouthOpenY", open);
        mouthRef.current = MOUTH_CLOSED;
      } else {
        mouthRef.current = stepMouth(mouthRef.current, deltaMs);
        if (mouthRef.current.open > 0) {
          driver.setParam("ParamMouthOpenY", mouthRef.current.open);
        }
      }

      // 视线：sleeping/error 状态由状态机禁用
      if (plan?.gazeEnabled) {
        gazeCurrentRef.current = lerpGaze(gazeCurrentRef.current, gazeTargetRef.current);
        driver.setParam("ParamEyeBallX", gazeCurrentRef.current.x);
        driver.setParam("ParamEyeBallY", gazeCurrentRef.current.y + plan.gazeOffsetY);
      }
    });
  }, [ready, isLive2D, ttsPlaying]);

  // 性能护栏（2.1 空闲 CPU≤8% / 2.6 简化）：窗口隐藏时停 ticker。
  // 其余策略已分布就位：空闲 30fps/说话 60fps（stateMachine.tickerFps）、
  // pixelRatio ≤2（core.ts）。电量/负载自动降级为 2.6 完整版，推迟。
  useEffect(() => {
    const stage = stageRef.current;
    if (!ready || !stage) return;
    const onVisibility = () => {
      if (document.visibilityState === "hidden") stage.app.ticker.stop();
      else stage.app.ticker.start();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [ready]);

  // 左键唤起输入框；右键弹上下文菜单。guard e.button 防止右键误触发 click。
  const handleClick = (e: ReactMouseEvent) => {
    if (e.button === 0) onActivate?.();
  };
  const handleContextMenu = (e: ReactMouseEvent) => {
    e.preventDefault();
    onContextMenu?.(e.clientX, e.clientY);
  };

  if (failed)
    return (
      <div className="character-stage" onClick={handleClick} onContextMenu={handleContextMenu}>
        <CharacterBadge />
      </div>
    );
  return (
    <div
      className="character-stage"
      ref={containerRef}
      data-skin={skin ? resolveSkinId(skin.id) : undefined}
      onClick={handleClick}
      onContextMenu={handleContextMenu}
    />
  );
}
