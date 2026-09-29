/**
 * CharacterStage —— 角色渲染层（M0-S3 起，M1-S1 皮肤系统）。
 *
 * 皮肤驱动（3.2/3.3/3.5）：resourceType=live2d 走 Cubism 模型。
 * 静态皮肤（PIXI Sprite 双路径）已随静态皮肤类型下线移除（2026-09-28）。
 * 能力档案来自 skin.json capabilities（HIYORI_PROFILE 硬编码已消除）。
 *
 * 加载成功：透明画布渲染，状态机把 (characterState, emotion) 实时翻译为
 * 动作/表情/参数；text.delta 驱动口型、光标驱动视线。加载失败降级回
 * CharacterBadge（ADR-0003 D2）。
 *
 * 换肤不闪白（ADR-0006 D10）：新舞台加载完成后才 dispose 旧舞台。
 *
 * 点击区域收敛（「点击区域过大」修复）：命中判定以 alpha 掩码为准——
 * Live2D 定期从渲染帧提取 + hitTest 分区兜底；掩码未命中时点击不唤起
 * 输入框、不触发反应、不拖拽（拖拽改自绘 startDragging，取代 canvas
 * 铺满的 data-tauri-drag-region）。窗口层透明区域鼠标穿透见
 * passthrough/useCursorPassthrough。
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import type { SkinSummary } from "../api/skinsClient";
import { useConversation } from "../store/conversation";
import { CharacterBadge } from "./CharacterBadge";
import { disposeStage, loadCharacterStage, type StageHandle } from "../live2d/core";
import * as PIXI from "pixi.js";
import { createDriver, type CharacterDriver } from "../live2d/driver";
import { lerpGaze, normalizeGaze, type GazeTarget, type StageRect } from "../live2d/gaze";
import { MOUTH_CLOSED, onDelta, stepMouth, volumeToOpen, type MouthState } from "../live2d/mouth";
import { ttsPlayer } from "../live2d/ttsPlayer";
import { useTTSState } from "../hooks/useTTS";
import { getCursor, reportCursor } from "../passthrough/cursorTracker";
import {
  bodyWiggleAngle,
  headPatAngleZ,
  headPatEnvelope,
  HEAD_PAT_PARAMS,
  reactionFor,
} from "../live2d/interactions";
import { buildMaskFromCanvas, maskOpaqueAt, type AlphaMask } from "../passthrough/alphaMask";
import {
  LOCOMOTION_STAY_MS,
  approachLerp,
  locomotionPose,
  locomotionTransform,
  type LocomotionPose,
} from "../live2d/locomotion";

/**
 * DEV 观测钩子（M-B B4/实测断言用）：挂到 window.__mochiDirector（仅 dev 构建），
 * GUI 自动化测试据此断言 playMotion 确实发生（避免“日志 accept 但未播放”的盲区）。
 */
export const devHook: {
  lastPlayMotion: { group: string; at: number } | null;
  /** M-C：最近提交到 director 的 reply 节拍（端到端实测断言用） */
  lastReplyCue: { actionId: string; channel: string; at: number } | null;
  /** M-D：命中判定探针（GUI 实测定位可点击点；随构建刷新实现） */
  hitTest: (x: number, y: number) => boolean;
} = {
  lastPlayMotion: null,
  lastReplyCue: null,
  hitTest: () => false,
};
import {
  resolveAnimation,
  EMOTION_PRESETS,
  FACE_REFLEX_PRESETS,
  type AnimationPlan,
  type ModelProfile,
} from "../live2d/stateMachine";
import { LOCOMOTION_ACTIONS, type Emotion, type LocomotionActionId } from "@mochi/protocol";
import {
  createDirectorState,
  submitCue,
  tickDirector,
  activeOn,
  type DirectorContext,
  type DirectorCue,
  type DirectorState,
} from "../live2d/actionDirector";
import {
  buildCue,
  isRepeatTap,
  toolReflexCues,
  pickIdleAction,
  IDLE_ROTATION_INTERVAL_MS,
  TAP_WINDOW_MS,
  HOLD_THRESHOLD_MS,
} from "../live2d/reflexRules";
import {
  beginSpeech,
  createCueScheduler,
  dueCues as dueReplyCues,
  endSpeech,
  resetCues as resetReplyCues,
  submitCue as scheduleReplyCue,
  type CueConverter,
} from "../cue/cueScheduler";
import { resolveAction } from "../live2d/actionRegistry";
import {
  createSampleWindow,
  decorationsPaused,
  effectiveFps,
  nextFpsLevel,
  type FpsLevel,
} from "../live2d/powerGuard";
import { useSettings } from "../store/settings";

/** §8 基线测量钩子：每秒刷新（fps 由窗口均帧耗推得 + 实测帧计数）。 */
function publishStats(avgFrameMs: number | null, framesLastSecond: number, level: FpsLevel) {
  const w = window as unknown as { __mochiStats?: Record<string, unknown> };
  w.__mochiStats = {
    fps: avgFrameMs !== null && avgFrameMs > 0 ? Math.round(1000 / avgFrameMs) : framesLastSecond,
    frameCount: framesLastSecond,
    powerLevel: level,
  };
}

/** 皮肤清单 → Live2D 能力档案（模型实际拥有的动作组/表情，状态机据此挑选）。
 *  paramIds（G1 Phase A）：模型加载后 dump 的参数 id 集，供包络能力核对/日志。 */
export function profileForSkin(skin: SkinSummary, paramIds: readonly string[] = []): ModelProfile {
  return {
    motionGroups: skin.capabilities?.motionGroups ?? [],
    expressions: skin.capabilities?.expressions ?? [],
    paramIds,
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
  const stageRef = useRef<StageHandle | null>(null);
  /** 换肤期间暂存的旧舞台：新舞台就绪后才销毁，避免闪白。 */
  const previousStageRef = useRef<StageHandle | null>(null);
  const driverRef = useRef<CharacterDriver | null>(null);
  const planRef = useRef<AnimationPlan | null>(null);
  const mouthRef = useRef<MouthState>(MOUTH_CLOSED);
  const gazeTargetRef = useRef<GazeTarget>({ x: 0, y: 0 });
  const gazeCurrentRef = useRef<GazeTarget>({ x: 0, y: 0 });
  /** 分区点击反应（2.4，仅 live2d）：点击时刻 + 类型，帧覆写期间消费 */
  const reactionRef = useRef<{ kind: "head" | "body"; startedAt: number } | null>(null);
  // 容器联动位置（I3/M-H）：持久状态，非 idle/超时自动回位；帧闭包读 ref
  const [locomotion, setLocomotion] = useState<LocomotionActionId>("come_back");
  const locomotionRef = useRef<LocomotionActionId>("come_back");
  locomotionRef.current = locomotion;
  const locomotionSinceRef = useRef(0);
  /** locomotion 姿态当前值（帧覆写指数趋近目标，避免瞬移） */
  const locomotionPoseRef = useRef<LocomotionPose>({
    dx: 0,
    dy: 0,
    scale: 1,
    bodyZ: 0,
    headZ: 0,
    bodyY: 0,
    headY: 0,
  });
  /** 模型原始宽高比（onModelReady 回传，位移量计算用） */
  const modelAspectRef = useRef(1);
  /** 命中掩码：null = 未就绪/降级，命中判定退回“整窗可交互”（旧行为） */
  const maskRef = useRef<AlphaMask | null>(null);
  /** 命中判定（视口坐标）：掩码 ∪ Live2D 分区；掩码就绪前恒 true */
  const hitTestRef = useRef<(x: number, y: number) => boolean>(() => true);
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
  // 表演节拍（M-C）：服务端 character.cue 队列 + 播报上下文（句对齐基准）
  const pendingCues = useConversation((s) => s.pendingCues);
  const speechText = useTTSState((s) => s.speechText);
  const speechStartedAt = useTTSState((s) => s.speechStartedAt);
  const speechDurationMs = useTTSState((s) => s.speechDurationMs);
  // 省电模式（2.6）：钉最低档 + 暂停装饰动画；事实源 sidecar，跨窗口同步
  const powerSave = useSettings((s) => s.powerSave);

  // DEV 观测钩子挂载（仅 dev 构建；release 无 window 副作用）
  useEffect(() => {
    if (import.meta.env.DEV) {
      (window as unknown as { __mochiDirector?: typeof devHook }).__mochiDirector = devHook;
      // M-D：命中判定探针绑定当前构建的实现（掩码就绪后自动生效）
      devHook.hitTest = (x: number, y: number) => hitTestRef.current(x, y);
      // M-C 调度器快照（端到端实测排查用）
      (window as unknown as { __mochiCueDebug?: () => unknown }).__mochiCueDebug = () => ({
        pending: cueSchedulerRef.current.pending.map((p) => p.cue.cueId),
        hasSpeech: cueSchedulerRef.current.speech !== null,
        starts: cueSchedulerRef.current.speech?.starts ?? null,
        fired: [...cueSchedulerRef.current.fired],
      });
    }
  }, []);

  // ---------------------------------------------------------------------------
  // Action Director（M-B）：本地反射与 one-shot 动作调度（face/body/effect 分通道）
  // ---------------------------------------------------------------------------
  const toolCalls = useConversation((s) => s.toolCalls);
  const directorRef = useRef<DirectorState>(createDirectorState());
  /** 帧闭包读的最新运行上下文（每渲染同步） */
  const directorCtxRef = useRef<DirectorContext>({
    state: "idle",
    speaking: false,
    dragging: false,
    decorationsPaused: false,
  });
  /** 连续轻戳时间戳（2s 窗口） */
  const tapsRef = useRef<number[]>([]);
  /** 按住/拖起定时器 + 拖拽中标记（守卫用） */
  const holdTimerRef = useRef<number | null>(null);
  const holdActiveAtRef = useRef<number | null>(null);
  /** 工具 chip 状态 diff 基准（上一状态表） */
  const toolStatusRef = useRef<Map<string, string>>(new Map());
  /** 帧闭包读的最新皮肤（帧覆写 effect 不随换肤重建） */
  const skinRef = useRef(skin);
  skinRef.current = skin;
  /** body 通道已启动处理的 cueId（幂等去重，Live2D P0 修复） */
  const bodyHandledRef = useRef<string | null>(null);
  /** 参数发现（G1 Phase A）：模型加载后 dump 的参数 id 集，供包络能力核对 */
  const paramIdsRef = useRef<string[]>([]);

  // 每渲染同步 director 上下文（帧闭包读 ref，不重建）
  directorCtxRef.current = {
    state: ttsPlaying ? "talking" : characterState,
    speaking: ttsPlaying,
    dragging: holdActiveAtRef.current !== null && Date.now() - holdActiveAtRef.current < 2000,
    decorationsPaused: decorationsPaused(powerLevelRef.current),
  };

  // ---------------------------------------------------------------------------
  // 表演节拍调度（M-C C3）：character.cue → 按 sync 与 TTS 对齐 → director
  // ---------------------------------------------------------------------------
  const cueSchedulerRef = useRef(createCueScheduler());

  // 新回合开始 → 作废上一回合未到期的节拍（旧 TTS 已被 stopSpeaking 停止）。
  // 注意：run 结束（activeRunId→null）时【不】作废——句对齐节拍要随 TTS 续播；
  // 「迟到不补演」在到达时判定（store），已入调度器的随新回合 reset。
  // 【声明顺序约束】本 effect 必须先于下方 drain effect：run.started 与
  // character.cue 同批到达时，effects 按声明序执行——先 reset 旧回合，
  // 再排水新 cue，否则刚入队的 cue 会被误清（实测 2026-09-28）
  const activeRunId = useConversation((s) => s.activeRunId);
  const prevRunIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (activeRunId !== null && activeRunId !== prevRunIdRef.current) {
      resetReplyCues(cueSchedulerRef.current);
    }
    prevRunIdRef.current = activeRunId;
  }, [activeRunId]);

  // 队列排水：新到达的 cue 提交调度器（ttl 到达即校验，过期丢弃）；
  // 已入调度器的从 store 移除（保持「待消费队列」语义干净）
  const consumePendingCues = useConversation((s) => s.consumePendingCues);
  useEffect(() => {
    if (pendingCues.length === 0) return;
    // locomotion 通道（I3/M-H）：白名单校验后取最后一条执行（到达即执行，
    // 忽略 sync——位移是 ~1s 的 CSS transition，无需句级对齐）；不进
    // 调度器（转换器只认 face/body）
    const locoHits: LocomotionActionId[] = [];
    for (const { cue } of pendingCues) {
      const lid = cue.channels.locomotion?.actionId;
      if (lid && (LOCOMOTION_ACTIONS as readonly string[]).includes(lid)) {
        locoHits.push(lid as LocomotionActionId);
      }
    }
    if (locoHits.length > 0) {
      const target = locoHits[locoHits.length - 1];
      setLocomotion(target);
      locomotionSinceRef.current = Date.now();
      if (import.meta.env.DEV) console.debug(`[locomotion] ${target}`);
    }
    for (const { cue, ts } of pendingCues) {
      scheduleReplyCue(cueSchedulerRef.current, cue, ts, Date.now());
    }
    consumePendingCues(pendingCues.length);
  }, [pendingCues, consumePendingCues]);

  // 自动回位：进入非 idle 状态（说话/思考要回中间）或停留超时 → come_back
  useEffect(() => {
    if (locomotion === "come_back") return;
    const timer = window.setInterval(() => {
      if (
        effectiveState !== "idle" ||
        Date.now() - locomotionSinceRef.current > LOCOMOTION_STAY_MS
      ) {
        setLocomotion("come_back");
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [locomotion, effectiveState]);

  // 播报上下文：开始（含真实/估算时长）→ beginSpeech；结束 → speech_end 提前到期
  const speechKeyRef = useRef(0);
  useEffect(() => {
    if (ttsPlaying && speechStartedAt > 0 && speechStartedAt !== speechKeyRef.current) {
      speechKeyRef.current = speechStartedAt;
      beginSpeech(cueSchedulerRef.current, speechText, speechDurationMs, Date.now());
    } else if (!ttsPlaying && speechKeyRef.current !== 0) {
      endSpeech(cueSchedulerRef.current, Date.now());
      speechKeyRef.current = 0;
    }
  }, [ttsPlaying, speechStartedAt, speechText, speechDurationMs]);

  /** 协议 cue → DirectorCue：经 buildCue 解析皮肤声明（冷却/时长），
   *  覆盖协议定值（cueId/priority/interruptPolicy/ttl）。帧闭包经 ref 读取。 */
  const cueConvertRef = useRef<CueConverter>(() => null);
  cueConvertRef.current = (proto, channel, now) => {
    const skinNow = skinRef.current;
    const actionId =
      channel === "face"
        ? (proto.channels.face?.emotion ?? "neutral")
        : (proto.channels.body?.actionId ?? "idle_neutral");
    const base = buildCue(actionId, {
      channel,
      source: proto.source, // reply=播报节拍（豁免守卫）；proactive=主动表演（M-D）
      now,
      actions: skinNow?.actions,
      ttlMs: proto.ttlMs,
      priority: proto.priority,
    });
    return {
      ...base,
      cueId: `${proto.cueId}:${channel}`,
      interruptPolicy: proto.interruptPolicy,
      createdAt: now,
    };
  };

  /** 反射入口：批量提交 cue（dev 下打点，B4 观测） */
  const submitReflexes = useCallback((cues: DirectorCue[]) => {
    const ctx = directorCtxRef.current;
    for (const cue of cues) {
      const verdict = submitCue(directorRef.current, cue, ctx, Date.now());
      if (import.meta.env.DEV) {
        console.debug(
          `[director] ${verdict.accepted ? "accept" : "reject"}(${verdict.accepted ? "" : verdict.reason}) ${cue.channel}:${cue.actionId} pri=${cue.priority}`,
        );
      }
    }
  }, []);

  // 工具生命周期反射：chip 状态流转 → cue（B3；确定性事件不经 LLM）
  useEffect(() => {
    const prev = toolStatusRef.current;
    let latest: { status: string; at: number } | null = null;
    for (const call of toolCalls) {
      if (prev.get(call.toolCallId) !== call.status) {
        prev.set(call.toolCallId, call.status);
        latest = { status: call.status, at: Date.now() };
      }
    }
    if (latest === null) return;
    if (!skin) return;
    const cues = toolReflexCues(latest.status as "running" | "success" | "error" | "denied", {
      now: latest.at,
      actions: skin.actions,
    });
    if (cues.length > 0) submitReflexes(cues);
  }, [toolCalls, skin, submitReflexes]);

  /** 追鼠标归一化目标：cursorTracker 最新光标 × 舞台矩形（含节流缓存）。
   *  只读 ref，useCallback 稳定 */
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
    return cursor.fresh ? normalizeGaze(cursor.x, cursor.y, entry.rect) : { x: 0, y: 0 };
  }, []);

  // 皮肤加载：id 变化 → cleanup 暂存旧舞台 → 新加载就绪后销毁旧的
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !skin) return;
    // 换装重试：清上一轮失败标记（badge 为 overlay，容器始终挂载，
    // 否则失败后 containerRef 被摘除、后续换装永远无法重新加载）
    setFailed(false);
    let cancelled = false;

    const url = `${skin.resourceBaseUrl}/${skin.modelFile ?? ""}`;
    const loading = loadCharacterStage(container, url);

    loading
      .then((loaded) => {
        // StrictMode 双挂载：卸载后才完成的加载立即销毁
        if (cancelled) {
          disposeStage(loaded);
          return;
        }
        stageRef.current = loaded;
        driverRef.current = createDriver(loaded);
        // 参数发现（G1 Phase A）：加载后 dump 一次，供包络能力核对与日志
        paramIdsRef.current = driverRef.current.dumpParamIds();
        console.info(
          `[mochi] model-params ${paramIdsRef.current.length} 个参数可探测` +
            (paramIdsRef.current.length === 0 ? "（dump 不可用，能力核对降级）" : ""),
        );
        // 新舞台就绪才销毁旧舞台：换肤全程有画面（ADR-0006 D10）
        if (previousStageRef.current) {
          disposeStage(previousStageRef.current);
          previousStageRef.current = null;
        }
        // 启动里程碑打点（performance.now 相对页面 timeOrigin）：
        // 1.1 冷启动验收 / 2.6 性能回归排查用，release 下经 macOS 统一日志可见
        console.info(`[mochi] character-ready(live2d) +${Math.round(performance.now())}ms`);
        onModelReady?.(loaded.modelWidth, loaded.modelHeight);
        modelAspectRef.current = loaded.modelWidth / loaded.modelHeight;
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
    skin?.resourceBaseUrl,
    skin?.modelFile,
    // 动作扩展包导入（G4）：motion 组集合变化须重建舞台才能播新组
    skin?.capabilities?.motionGroups?.join(","),
    onModelReady,
    onFallback,
  ]);

  // 彻底卸载：残留舞台一并销毁
  useEffect(
    () => () => {
      if (stageRef.current) disposeStage(stageRef.current);
      if (previousStageRef.current) disposeStage(previousStageRef.current);
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
      const rect = container.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return true;
      if (maskOpaqueAt(mask, x - rect.left, y - rect.top, rect.width, rect.height)) return true;
      // 掩码未命中：再试分区（动作中轮廓漂移的兜底）
      return driver !== null && reactionFor(driver.hitTestAt(x, y)) !== null;
    };
    onHitTestReady?.((x: number, y: number) => hitTestRef.current(x, y));
    return () => {
      hitTestRef.current = () => true;
      onHitTestReady?.(null);
    };
  }, [onHitTestReady]);

  // 掩码构建：Live2D 从渲染帧提取并低频刷新（初帧延迟等 idle 就位）。
  // 提取失败保留旧掩码，不阻断交互。
  useEffect(() => {
    if (!ready || !skin) return;
    const stage = stageRef.current;
    if (!stage) return;
    let cancelled = false;
    let refreshTimer = 0;
    let firstTimer = 0;
    const refresh = () => {
      if (cancelled) return;
      try {
        const renderer = stage.app.renderer as PIXI.Renderer;
        maskRef.current = buildMaskFromCanvas(renderer.extract.canvas(stage.app.stage));
      } catch (err) {
        // 提取失败：保留旧掩码，下个周期重试；打点便于发现污染/权限类硬错
        console.warn("[mochi] Live2D 掩码提取失败：", err);
      }
    };
    firstTimer = window.setTimeout(refresh, LIVE2D_MASK_FIRST_DELAY_MS);
    refreshTimer = window.setInterval(refresh, LIVE2D_MASK_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(firstTimer);
      window.clearInterval(refreshTimer);
      maskRef.current = null; // 换肤/卸载：旧轮廓作废，判定退回旧行为直到新掩码就绪
    };
  }, [
    ready,
    skin?.id,
    skin?.resourceBaseUrl,
    skin?.modelFile,
    skin?.capabilities?.motionGroups?.join(","),
  ]);

  // 状态机：(有效状态, 情绪) → 动画计划；
  // 性能护栏（2.6）掩码：降档后改写 tickerFps + 关装饰动画，档位变化时重放。
  useEffect(() => {
    const driver = driverRef.current;
    if (!driver || !ready || !skin) return;
    const applyGuarded = () => {
      const level = powerLevelRef.current;
      const raw = resolveAnimation(effectiveState, emotion, profileForSkin(skin));
      const plan: AnimationPlan = {
        ...raw,
        tickerFps: effectiveFps(raw.tickerFps, level) as AnimationPlan["tickerFps"],
        bodySway: raw.bodySway && !decorationsPaused(level),
      };
      planRef.current = plan;
      driver.applyPlan(plan);
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
      stage.app.ticker.maxFPS = effectiveFps(planRef.current?.tickerFps ?? 60, next);
      reapplyPlanRef.current();
    };
    evaluate(); // 省电开关切换时立即生效
    const timer = window.setInterval(evaluate, 1000);
    return () => {
      stage.app.ticker?.remove(sample);
      window.clearInterval(timer);
    };
  }, [stageEpoch, powerSave]);

  // 闲置轮换池（批次 3 I2）：idle 状态下低频触发小动作，权重随闲置时长渐进
  // （刚闲置安静 → 中期东张西望/哼歌/伸懒腰 → 久置偏向打盹）。非 idle 交互
  // 即重置计时；全部走包络可演项，proactive 源不抢播报节拍。
  const idleSinceRef = useRef(Date.now());
  useEffect(() => {
    if (!ready) return;
    const timer = window.setInterval(() => {
      const now = Date.now();
      if (effectiveState !== "idle") {
        idleSinceRef.current = now;
        return;
      }
      const actionId = pickIdleAction(now - idleSinceRef.current, Math.random());
      if (!actionId) return;
      idleSinceRef.current = now - 60_000; // 触发后视为仍有活动，回退到中期档
      submitReflexes([
        buildCue(actionId, {
          channel: "body",
          source: "proactive",
          now,
          actions: skinRef.current?.actions,
        }),
      ]);
    }, IDLE_ROTATION_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [ready, effectiveState, submitReflexes]);

  // 口型（2.3）：每个 text.delta 触发一次张嘴；帧覆写负责衰减与闭合
  useEffect(() => {
    if (lastTextDeltaAt > 0) {
      mouthRef.current = onDelta(mouthRef.current, lastTextDelta);
    }
  }, [lastTextDeltaAt, lastTextDelta]);

  // 光标追踪（2.4 追鼠标的事实源）：mousemove 上报
  // cursorTracker；桌面端穿透层轮询也在上报（光标处于穿透忽略区/窗外时
  // mousemove 收不到，轮询是关键补充）。消费方在各自帧覆写里归一化。
  useEffect(() => {
    if (!ready) return;
    const onMove = (e: MouseEvent) => reportCursor(e.clientX, e.clientY);
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

      // Action Director 推进（M-B）：one-shot 到期/出队结算；
      // body 通道【幂等消费】每个新 cue（按 cueId 去重，P0 修复：
      // submitCue 置 active 的即时动作与出队提升的动作走同一条启动路径，
      // 不再依赖 tick.started）；播完自动回落 idle 组，状态 loop 接管
      const nowMs = Date.now();
      tickDirector(directorRef.current, directorCtxRef.current, nowMs);
      // 表演节拍（M-C）：到期的 reply cue 提交 director（与反射同一条提交路径）
      for (const c of dueReplyCues(cueSchedulerRef.current, nowMs, cueConvertRef.current)) {
        submitCue(directorRef.current, c, directorCtxRef.current, nowMs);
        devHook.lastReplyCue = { actionId: c.actionId, channel: c.channel, at: nowMs };
      }
      const skinNow = skinRef.current;
      const bodyAction = activeOn(directorRef.current, "body");
      if (bodyAction !== null && bodyHandledRef.current !== bodyAction.cue.cueId && skinNow) {
        bodyHandledRef.current = bodyAction.cue.cueId;
        const actionPlan = resolveAction(
          bodyAction.cue.actionId,
          skinNow,
          profileForSkin(skinNow, paramIdsRef.current),
        );
        // G1：包络执行下沉 driver（motion/声明包络/内置兑底统一入口），组件层纯调度
        driver.applyAction(
          {
            requestedId: actionPlan.requestedId,
            motionGroup: actionPlan.motionGroup,
            paramEnvelope: actionPlan.paramEnvelope,
          },
          {
            startedAtMs: bodyAction.startedAt,
            priority: bodyAction.cue.priority >= 80 ? "force" : "normal",
          },
        );
        if (actionPlan.motionGroup) {
          devHook.lastPlayMotion = { group: actionPlan.motionGroup, at: nowMs };
        }
      }

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

      // face 通道（M-B）：表情参数覆写——在状态机表情预设之后写入，
      // one-shot 结束后停写，状态机计划自然回落（face/body 并行不清除）。
      // 查找顺序：情绪预设 → 反射专用预设（worried）
      const face = activeOn(directorRef.current, "face");
      if (face !== null && !plan?.eyesClosed) {
        const preset =
          EMOTION_PRESETS[face.cue.actionId as Emotion] ?? FACE_REFLEX_PRESETS[face.cue.actionId];
        if (preset) {
          for (const [id, v] of Object.entries(preset)) driver.setParam(id, v);
        }
      }

      // body 参数包络逐帧应用已下沉 driver（G1，见 driver.applyAction；
      // 包络叠在 face 表情与状态机预设之后（最优先）的顺序在 driver 内保持）

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

      // locomotion 姿态叠加（I3/M-H）：位移走 CSS transform（渲染层），
      // 倚靠/趴伏姿态走参数趋近；写在包络应用之后会被包络覆盖——
      // 「包络最优先」顺序不变。容器量测每帧重取太贵，250ms 节流缓存复用。
      const loco = locomotionRef.current;
      const rectNow = stageRectRef.current?.rect;
      if (rectNow && modelAspectRef.current > 0) {
        const targetPose = locomotionPose(
          loco,
          rectNow.width,
          rectNow.height,
          modelAspectRef.current,
        );
        const cur = locomotionPoseRef.current;
        cur.dx = approachLerp(cur.dx, targetPose.dx);
        cur.dy = approachLerp(cur.dy, targetPose.dy);
        cur.scale = approachLerp(cur.scale, targetPose.scale);
        cur.bodyZ = approachLerp(cur.bodyZ, targetPose.bodyZ);
        cur.headZ = approachLerp(cur.headZ, targetPose.headZ);
        cur.bodyY = approachLerp(cur.bodyY, targetPose.bodyY);
        cur.headY = approachLerp(cur.headY, targetPose.headY);
        if (cur.bodyZ !== 0) driver.setParam("ParamBodyAngleZ", cur.bodyZ);
        if (cur.headZ !== 0) driver.setParam("ParamAngleZ", cur.headZ);
        if (cur.bodyY !== 0) driver.setParam("ParamBodyAngleY", cur.bodyY);
        if (cur.headY !== 0) driver.setParam("ParamAngleY", cur.headY);
      }
    });
  }, [ready, ttsPlaying]);

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
    if (driver !== null && reactionRef.current === null) {
      const kind = reactionFor(driver.hitTestAt(e.clientX, e.clientY));
      if (kind !== null) reactionRef.current = { kind, startedAt: Date.now() };
    }
    // 反射（M-B）：拖拽链 tap 拍——单击 → body nod（轻拍回应）；
    // 连续轻戳（2s 内 ≥3 次）→ surprised（连续戳 ≠ 轻拍，冷却内不重复）
    const nowMs = Date.now();
    tapsRef.current = [...tapsRef.current.filter((t) => nowMs - t <= TAP_WINDOW_MS), nowMs];
    if (skinRef.current) {
      if (isRepeatTap(tapsRef.current, nowMs)) {
        submitReflexes([
          buildCue("surprised", {
            channel: "body",
            source: "reflex",
            now: nowMs,
            actions: skinRef.current.actions,
          }),
        ]);
      } else {
        submitReflexes([
          buildCue("nod", {
            channel: "body",
            source: "reflex",
            now: nowMs,
            actions: skinRef.current.actions,
          }),
        ]);
      }
    }
    onActivate?.();
  };
  // 拖拽（1.3）：命中角色才可拖动（自绘 startDragging，取代铺满画布的
  // data-tauri-drag-region——透明区域不再“抓住空气”拖窗）；浏览器环境无操作
  const handlePointerDown = (e: ReactMouseEvent) => {
    if (e.button !== 0) return;
    if (!hitTestRef.current(e.clientX, e.clientY)) return;
    // 反射（M-B）：按住超过阈值（拖起/拿起）→ surprised。
    // OS 接管拖窗后 pointerup 不可靠，定时器式判定；用户交互级优先级过守卫
    if (holdTimerRef.current === null) {
      holdTimerRef.current = window.setTimeout(() => {
        holdTimerRef.current = null;
        holdActiveAtRef.current = Date.now();
        if (skinRef.current) {
          submitReflexes([
            buildCue("surprised", {
              channel: "body",
              source: "reflex",
              now: Date.now(),
              actions: skinRef.current.actions,
              priority: 80,
            }),
          ]);
        }
      }, HOLD_THRESHOLD_MS);
    }
    if ("__TAURI_INTERNALS__" in window) void getCurrentWindow().startDragging();
  };
  // 抬起：取消未到阈值的「被拿起」定时；若刚发生过拖起，拖拽链收尾
  // release → recover（idle_neutral 回状态 loop；OS 拖窗期间 pointerup
  // 可能不达——届时 one-shot 自然到期由状态 loop 收口，等效 recover）
  const handlePointerUp = () => {
    if (holdTimerRef.current !== null) {
      window.clearTimeout(holdTimerRef.current);
      holdTimerRef.current = null;
    }
    if (holdActiveAtRef.current !== null && skinRef.current) {
      holdActiveAtRef.current = null;
      submitReflexes([
        buildCue("idle_neutral", {
          channel: "body",
          source: "reflex",
          now: Date.now(),
          actions: skinRef.current.actions,
          priority: 80,
        }),
      ]);
    }
  };
  const handleContextMenu = (e: ReactMouseEvent) => {
    e.preventDefault();
    onContextMenu?.(e.clientX, e.clientY);
  };

  // 失败降级：badge 以 overlay 叠加（容器不卸载——containerRef 持续有效，
  // 换装即重试；旧画布以 CSS 隐藏避免残影，引用仍留给新加载就绪时销毁）
  const activePose = locomotionPoseRef.current;
  const transformed = activePose.dx !== 0 || activePose.dy !== 0 || activePose.scale !== 1;
  return (
    <div
      className={`character-stage${failed ? " character-stage--failed" : ""}${transformed ? " character-stage--locomoted" : ""}`}
      ref={containerRef}
      data-skin={skin?.id}
      data-locomotion={locomotion}
      style={transformed ? { transform: locomotionTransform(activePose) } : undefined}
      onClick={handleClick}
      onContextMenu={handleContextMenu}
      onPointerDown={handlePointerDown}
      onPointerUp={handlePointerUp}
    >
      {failed ? <CharacterBadge /> : null}
    </div>
  );
}
