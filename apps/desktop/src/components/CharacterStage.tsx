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
 *
 * 点击区域收敛（「点击区域过大」修复）：命中判定以 alpha 掩码为准——
 * 静态皮肤从源图构建、Live2D 定期从渲染帧提取 + hitTest 分区兜底；
 * 掩码未命中时点击不唤起输入框、不触发反应、不拖拽（拖拽改自绘
 * startDragging，取代 canvas 铺满的 data-tauri-drag-region）。窗口层的
 * 透明区域鼠标穿透见 passthrough/useCursorPassthrough。
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { resolveSkinId, type SkinSummary } from "../api/skinsClient";
import { useConversation } from "../store/conversation";
import { CharacterBadge } from "./CharacterBadge";
import { disposeStage, loadCharacterStage, type StageHandle } from "../live2d/core";
import * as PIXI from "pixi.js";
import { createDriver, type CharacterDriver } from "../live2d/driver";
import { lerpGaze, normalizeGaze, type GazeTarget, type StageRect } from "../live2d/gaze";
import { MOUTH_CLOSED, onDelta, stepMouth, volumeToOpen, type MouthState } from "../live2d/mouth";
import { ttsPlayer } from "../live2d/ttsPlayer";
import { useTTSState } from "../hooks/useTTS";
import { MAX_STATIC_UPSCALE } from "../layout/characterLayout";
import { disposeStaticStage, loadStaticStage, type StaticStageHandle } from "../live2d/staticCore";
import {
  createStaticDriver,
  type StaticAnimationPlan,
  type StaticDriver,
} from "../live2d/staticDriver";
import { resolveStaticAnimation } from "../live2d/staticStateMachine";
import { clickBounce, gazeLean } from "../live2d/staticInteractions";
import {
  IDLE_DELAY_MS,
  nextIdleGap,
  pickIdleAction,
  type IdleAction,
  type IdleActionId,
} from "../live2d/idleBehaviors";
import { getCursor, reportCursor } from "../passthrough/cursorTracker";
import {
  bodyWiggleAngle,
  headPatAngleZ,
  headPatEnvelope,
  HEAD_PAT_PARAMS,
  reactionFor,
} from "../live2d/interactions";
import {
  buildMaskFromCanvas,
  buildMaskFromImage,
  maskOpaqueAt,
  type AlphaMask,
} from "../passthrough/alphaMask";

/** 掩码不透明占比（诊断打点用）。 */
function opaqueRatio(mask: AlphaMask): number {
  let n = 0;
  for (const v of mask.alpha) if (v >= 16) n += 1;
  return n / mask.alpha.length;
}
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

/** §8 基线测量钩子：每秒刷新（fps 由窗口均帧耗推得 + 实测帧计数）。 */
function publishStats(avgFrameMs: number | null, framesLastSecond: number, level: FpsLevel) {
  const w = window as unknown as { __mochiStats?: Record<string, unknown> };
  w.__mochiStats = {
    fps: avgFrameMs !== null && avgFrameMs > 0 ? Math.round(1000 / avgFrameMs) : framesLastSecond,
    frameCount: framesLastSecond,
    powerLevel: level,
  };
}

/** §诊断：追鼠标链路状态发布到 window.__mochiGaze（devtools 可读；
 *  target 恒 0 = 光标样本没进来（穿透轮询/mousemove 断供））。 */
function publishGazeDebug(
  target: GazeTarget,
  current: GazeTarget,
  lean: { dx: number; dy: number; rotation: number },
): void {
  const w = window as unknown as { __mochiGaze?: Record<string, unknown> };
  w.__mochiGaze = { target, current, lean, at: performance.now() };
}

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
  /** 命中判定就绪/更新回调：App 汇入鼠标穿透判定（透明区不拦截）。
   *  回调内部读 ref，掩码刷新无需重发；卸载传 null 恢复“整窗可交互” */
  onHitTestReady?: (hit: ((x: number, y: number) => boolean) | null) => void;
}

/** Live2D 掩码刷新间隔（ms）：动作轮廓漂移有限，低频重提取足够。 */
const LIVE2D_MASK_REFRESH_MS = 4000;
/** 首次提取延迟（ms）：等 idle 动作第一帧就位，轮廓更接近常态。 */
const LIVE2D_MASK_FIRST_DELAY_MS = 300;

export function CharacterStage({
  skin,
  onActivate,
  onContextMenu,
  onModelReady,
  onFallback,
  onHitTestReady,
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
  /** 分区点击反应（2.4，仅 live2d）：点击时刻 + 类型，帧覆写期间消费 */
  const reactionRef = useRef<{ kind: "head" | "body"; startedAt: number } | null>(null);
  /** 命中掩码：null = 未就绪/降级，命中判定退回“整窗可交互”（旧行为） */
  const maskRef = useRef<AlphaMask | null>(null);
  /** 命中判定（视口坐标）：掩码 ∪ Live2D 分区；掩码就绪前恒 true */
  const hitTestRef = useRef<(x: number, y: number) => boolean>(() => true);
  /** 静态皮肤点击反馈时刻（果冻弹跳起算点）；包络归零后置 null */
  const staticReactionRef = useRef<{ startedAt: number } | null>(null);
  /** 静态皮肤当前动画计划（休眠/出错时停追鼠标） */
  const staticPlanRef = useRef<StaticAnimationPlan | null>(null);
  /** 闲置小动作调度状态（2.8，仅 static）：最近交互时刻 / 当前动作 / 下次时刻 */
  const idleRef = useRef<{
    lastActiveAt: number;
    action: { def: IdleAction; startedAt: number } | null;
    nextAt: number;
    lastId: IdleActionId | undefined;
  }>({
    lastActiveAt: Date.now(),
    action: null,
    nextAt: Date.now() + IDLE_DELAY_MS,
    lastId: undefined,
  });
  /** 光标移动检测的上一样本（>10px 视为用户活动，刷新闲置计时） */
  const idleCursorPrevRef = useRef<{ x: number; y: number } | null>(null);
  /** 对话进行中视为活动（覆写闭包读，避免重建） */
  const busyStateRef = useRef(false);
  /** 舞台矩形缓存（每帧 getBoundingClientRect 会强制布局，250ms 节流） */
  const stageRectRef = useRef<{ rect: StageRect; at: number } | null>(null);
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);
  // 舞台换代计数：快速换肤（模型缓存命中）时 setReady(false) 与 setReady(true)
  // 会被 React 合并成同一次渲染，ready 依赖的 effect 察觉不到舞台已更换，
  // 闭包里残留已销毁的旧舞台（ticker=null → 报错卸载）。epoch 强制重建。
  const [stageEpoch, setStageEpoch] = useState(0);
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

  /** 舞台矩形 → 交互参考矩形：静态皮肤取精灵实际矩形（源图掩码是精灵轮廓，
   *  映射整舞台会错位——精灵只占底部中央，窗口还有宽度下限撑宽）；
   *  live2d 的掩码来自整画布提取，维持舞台矩形 */
  const refitToSprite = useCallback((rect: StageRect): StageRect => {
    const driver = driverRef.current;
    if (driver?.kind !== "static") return rect;
    const sr = driver.spriteRect();
    return {
      left: rect.left + sr.left,
      top: rect.top + sr.top,
      width: sr.width,
      height: sr.height,
    };
  }, []);

  /** 追鼠标归一化目标：cursorTracker 最新光标 × 舞台矩形（含节流缓存）。
   *  双路径共用（live2d 眼球 / static 侧倾），只读 ref，useCallback 稳定 */
  const stageGazeTarget = useCallback((): GazeTarget => {
    const container = containerRef.current;
    if (!container) return { x: 0, y: 0 };
    const now = performance.now();
    let entry = stageRectRef.current;
    if (!entry || now - entry.at > 250) {
      entry = { rect: container.getBoundingClientRect(), at: now };
      stageRectRef.current = entry;
    }
    const cursor = getCursor();
    return cursor.fresh
      ? normalizeGaze(cursor.x, cursor.y, refitToSprite(entry.rect))
      : { x: 0, y: 0 };
  }, []);

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
        setStageEpoch((n) => n + 1);
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

  // 命中判定：掩码采样 + Live2D 分区兜底。函数体读 ref（掩码/驱动/容器），
  // 构建/刷新后无需重建闭包；App 侧经 onHitTestReady 拿到同一函数做穿透
  useEffect(() => {
    hitTestRef.current = (x: number, y: number) => {
      const container = containerRef.current;
      const mask = maskRef.current;
      const driver = driverRef.current;
      if (!container || !mask) return true; // 未就绪/降级：保持旧行为
      const rect = refitToSprite(container.getBoundingClientRect());
      if (rect.width === 0 || rect.height === 0) return true;
      if (maskOpaqueAt(mask, x - rect.left, y - rect.top, rect.width, rect.height)) return true;
      // 掩码未命中：Live2D 再试分区（动作中轮廓漂移的兜底；静态皮肤无分区）
      return driver?.kind === "live2d" && reactionFor(driver.hitTestAt(x, y)) !== null;
    };
    onHitTestReady?.((x: number, y: number) => hitTestRef.current(x, y));
    return () => {
      hitTestRef.current = () => true;
      onHitTestReady?.(null);
    };
  }, [onHitTestReady]);

  // 掩码构建：静态皮肤从源图一次性构建；Live2D 从渲染帧提取并低频刷新
  // （初帧延迟等 idle 就位）。提取失败保留旧掩码，不阻断交互。
  useEffect(() => {
    if (!ready || !skin) return;
    const stage = stageRef.current;
    if (!stage) return;
    const live2d = skin.resourceType === "live2d";
    const url = live2d
      ? `${skin.resourceBaseUrl}/${skin.modelFile ?? ""}`
      : `${skin.resourceBaseUrl}/${skin.imageFile ?? "avatar.png"}`;
    let cancelled = false;
    let refreshTimer = 0;
    let firstTimer = 0;
    if (live2d) {
      const refresh = () => {
        if (cancelled) return;
        try {
          const renderer = (stage as StageHandle).app.renderer as PIXI.Renderer;
          maskRef.current = buildMaskFromCanvas(
            renderer.extract.canvas((stage as StageHandle).app.stage),
          );
        } catch (err) {
          // 提取失败：保留旧掩码，下个周期重试；打点便于发现污染/权限类硬错
          console.warn("[mochi] Live2D 掩码提取失败：", err);
        }
      };
      firstTimer = window.setTimeout(refresh, LIVE2D_MASK_FIRST_DELAY_MS);
      refreshTimer = window.setInterval(refresh, LIVE2D_MASK_REFRESH_MS);
    } else {
      buildMaskFromImage(url)
        .then((mask) => {
          if (cancelled) return;
          maskRef.current = mask;
          console.info(
            `[mochi] 静态皮肤命中掩码就绪 ${mask.width}x${mask.height}（不透明 ${(opaqueRatio(mask) * 100).toFixed(1)}%）`,
          );
        })
        .catch((err) => {
          // 掩码构建失败：命中判定保持“整窗可交互”，不影响功能；但必须可见
          console.error("[mochi] 静态皮肤掩码构建失败（穿透将不生效）：", err);
        });
    }
    return () => {
      cancelled = true;
      window.clearTimeout(firstTimer);
      window.clearInterval(refreshTimer);
      maskRef.current = null; // 换肤/卸载：旧轮廓作废，判定退回旧行为直到新掩码就绪
    };
  }, [
    ready,
    skin?.id,
    skin?.resourceType,
    skin?.resourceBaseUrl,
    skin?.imageFile,
    skin?.modelFile,
  ]);

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
        staticPlanRef.current = raw;
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
  // 附带 window.__mochiStats（§8 基线测量钩子：fps + 当前档位，devtools 可读）。
  useEffect(() => {
    const stage = stageRef.current;
    if (!ready || !stage) return;
    const sampleWindow = createSampleWindow();
    let frameCount = 0;
    const sample = () => {
      sampleWindow.push(stage.app.ticker.deltaMS, performance.now());
      frameCount += 1;
    };
    stage.app.ticker.add(sample);

    const evaluate = () => {
      const avg = sampleWindow.average();
      const next = nextFpsLevel(powerLevelRef.current, avg, powerSave);
      publishStats(avg, frameCount, next);
      frameCount = 0;
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
      stage.app.ticker?.remove(sample);
      window.clearInterval(timer);
    };
  }, [stageEpoch, powerSave]);

  // 口型（2.3，仅 live2d）：每个 text.delta 触发一次张嘴；帧覆写负责衰减与闭合
  useEffect(() => {
    if (!isLive2D) return;
    if (lastTextDeltaAt > 0) {
      mouthRef.current = onDelta(mouthRef.current, lastTextDelta);
    }
  }, [isLive2D, lastTextDeltaAt, lastTextDelta]);

  // 对话进行中（talking/thinking/working）视为用户活动，闲置小动作不打扰
  useEffect(() => {
    busyStateRef.current =
      effectiveState === "talking" || effectiveState === "thinking" || effectiveState === "working";
  }, [effectiveState]);

  // 光标追踪（2.4 追鼠标的事实源，双路径皮肤共用）：mousemove 上报
  // cursorTracker；桌面端穿透层轮询也在上报（光标处于穿透忽略区/窗外时
  // mousemove 收不到，轮询是关键补充）。消费方在各自帧覆写里归一化。
  useEffect(() => {
    if (!ready) return;
    const onMove = (e: MouseEvent) => reportCursor(e.clientX, e.clientY);
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [ready]);

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

      // 视线：sleeping/error 状态由状态机禁用；目标从 cursorTracker 每帧
      // 重算（穿透忽略区/窗外也追踪，normalizeGaze 自带 clamp）
      if (plan?.gazeEnabled) {
        gazeTargetRef.current = stageGazeTarget();
        gazeCurrentRef.current = lerpGaze(gazeCurrentRef.current, gazeTargetRef.current);
        driver.setParam("ParamEyeBallX", gazeCurrentRef.current.x);
        driver.setParam("ParamEyeBallY", gazeCurrentRef.current.y + plan.gazeOffsetY);
      }

      // 分区点击反应（2.4）：摸头=眼笑+嘴角+头偏包络；戳身体=衰减摆动。
      // 包络归零后自然停止（不再下发参数，回落状态机计划）。
      const reaction = reactionRef.current;
      if (reaction !== null) {
        const elapsed = Date.now() - reaction.startedAt;
        if (reaction.kind === "head") {
          const env = headPatEnvelope(elapsed);
          if (env > 0) {
            for (const [id, v] of Object.entries(HEAD_PAT_PARAMS)) driver.setParam(id, v * env);
            driver.setParam("ParamAngleZ", headPatAngleZ(elapsed));
          } else reactionRef.current = null;
        } else {
          const angle = bodyWiggleAngle(elapsed);
          if (angle !== 0) driver.setParam("ParamBodyAngleX", angle);
          else reactionRef.current = null;
        }
      }
    });
  }, [ready, isLive2D, ttsPlaying]);

  // 每帧变换覆写（仅 static，2.4 静态路径）：追鼠标侧倾 + 点击果冻弹跳。
  // 休眠/出错态停追（睡着还盯着鼠标不对劲）；包络归零后反应自然结束
  useEffect(() => {
    const driver = driverRef.current;
    if (!ready || !driver || driver.kind !== "static") return;
    return driver.addFrameOverride((_tSec, base) => {
      let tr = base;
      const plan = staticPlanRef.current;
      if (!plan?.sleeping && !plan?.error) {
        gazeTargetRef.current = stageGazeTarget();
        gazeCurrentRef.current = lerpGaze(gazeCurrentRef.current, gazeTargetRef.current);
        const lean = gazeLean(gazeCurrentRef.current.x, gazeCurrentRef.current.y);
        publishGazeDebug(gazeTargetRef.current, gazeCurrentRef.current, lean);
        tr = {
          ...tr,
          dx: tr.dx + lean.dx,
          dy: tr.dy + lean.dy,
          rotation: tr.rotation + lean.rotation,
        };
      }
      // 闲置小动作（2.8）：无点击/光标移动/对话 且非降档装饰暂停时随机播放；
      // 动作结束（apply 返回 null）排下一次，连续重复同一个会被排除
      const idle = idleRef.current;
      const cursorNow = getCursor();
      if (idleCursorPrevRef.current === null) idleCursorPrevRef.current = { ...cursorNow };
      const moved =
        Math.abs(cursorNow.x - idleCursorPrevRef.current.x) +
        Math.abs(cursorNow.y - idleCursorPrevRef.current.y);
      idleCursorPrevRef.current = { x: cursorNow.x, y: cursorNow.y };
      if (moved > 10 || busyStateRef.current) idle.lastActiveAt = Date.now();
      if (
        idle.action === null &&
        !plan?.sleeping &&
        !plan?.error &&
        !decorationsPaused(powerLevelRef.current) &&
        Date.now() - idle.lastActiveAt >= IDLE_DELAY_MS &&
        Date.now() >= idle.nextAt
      ) {
        idle.action = { def: pickIdleAction(idle.lastId), startedAt: Date.now() };
        idle.lastId = idle.action.def.id;
      }
      if (idle.action !== null) {
        const delta = idle.action.def.apply(Date.now() - idle.action.startedAt);
        if (delta) {
          tr = {
            ...tr,
            dx: tr.dx + delta.dx,
            dy: tr.dy + delta.dy,
            rotation: tr.rotation + delta.rotation,
            scaleX: (tr.scaleX ?? tr.scale) * delta.sx,
            scaleY: (tr.scaleY ?? tr.scale) * delta.sy,
          };
        } else {
          idle.action = null;
          idle.nextAt = Date.now() + nextIdleGap();
        }
      }
      const reaction = staticReactionRef.current;
      if (reaction !== null) {
        const bounce = clickBounce(Date.now() - reaction.startedAt);
        if (bounce) {
          tr = {
            ...tr,
            dy: tr.dy + bounce.hop,
            scaleX: (tr.scaleX ?? tr.scale) * bounce.sx,
            scaleY: (tr.scaleY ?? tr.scale) * bounce.sy,
          };
        } else {
          staticReactionRef.current = null;
        }
      }
      return tr;
    });
  }, [ready, isLive2D, stageGazeTarget]);

  // 性能护栏（2.1 空闲 CPU≤8% / 2.6 简化）：窗口隐藏时停 ticker。
  // 其余策略已分布就位：空闲 30fps/说话 60fps（stateMachine.tickerFps）、
  // pixelRatio ≤2（core.ts）。电量/负载自动降级为 2.6 完整版，推迟。
  useEffect(() => {
    const stage = stageRef.current;
    if (!ready || !stage) return;
    const onVisibility = () => {
      if (document.visibilityState === "hidden") stage.app.ticker?.stop();
      else stage.app.ticker?.start();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [ready, stageEpoch]);

  // 左键：命中角色才交互（2.4 分区差异化反应 + 唤起输入框）；透明区域
  // 不唤起不反应（桌面端穿透层已把点击放行给下层应用）。右键弹上下文菜单。
  const handleClick = (e: ReactMouseEvent) => {
    if (e.button !== 0) return;
    if (!hitTestRef.current(e.clientX, e.clientY)) return;
    const driver = driverRef.current;
    if (driver !== null && driver.kind === "live2d" && reactionRef.current === null) {
      const kind = reactionFor(driver.hitTestAt(e.clientX, e.clientY));
      if (kind !== null) reactionRef.current = { kind, startedAt: Date.now() };
    }
    // 静态皮肤：整体果冻弹跳（无分区概念），叠加在既有动画之上
    if (driver !== null && driver.kind === "static" && staticReactionRef.current === null) {
      staticReactionRef.current = { startedAt: Date.now() };
    }
    idleRef.current.lastActiveAt = Date.now(); // 点击重置闲置计时（2.8）
    onActivate?.();
  };
  // 拖拽（1.3）：命中角色才可拖动（自绘 startDragging，取代铺满画布的
  // data-tauri-drag-region——透明区域不再“抓住空气”拖窗）；浏览器环境无操作
  const handlePointerDown = (e: ReactMouseEvent) => {
    if (e.button !== 0) return;
    if (!hitTestRef.current(e.clientX, e.clientY)) return;
    if ("__TAURI_INTERNALS__" in window) void getCurrentWindow().startDragging();
  };
  const handleContextMenu = (e: ReactMouseEvent) => {
    e.preventDefault();
    onContextMenu?.(e.clientX, e.clientY);
  };

  if (failed)
    return (
      <div
        className="character-stage"
        onClick={handleClick}
        onContextMenu={handleContextMenu}
        onPointerDown={handlePointerDown}
      >
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
      onPointerDown={handlePointerDown}
    />
  );
}
