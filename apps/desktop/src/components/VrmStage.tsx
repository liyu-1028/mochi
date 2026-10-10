/**
 * VrmStage —— VRM 角色渲染层（ADR-0011 P0，D8 双栈的 VRM 路径）。
 *
 * 与 CharacterStage（Live2D 路径）共享全部渲染无关行为模块
 * （actionDirector/reflexRules/cueScheduler/gaze/mouth/ttsPlayer/locomotion/
 * powerGuard——character/ 顶层）；渲染执行换 VrmDriver（四层合成）。
 * 命中走 Raycaster 几何（无 alpha 掩码）；locomotion 位移沿用 CSS
 * transform（场景内 root 位移为 P3）。
 *
 * 调度推进（director/cue 排水/幂等消费）在本组件独立 rAF 循环——
 * VRM 驱动的渲染循环在 driver 内部，两者解耦（渲染档位不影响调度节拍）。
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { LOCOMOTION_ACTIONS, type LocomotionActionId } from "@mochi/protocol";
import { loadVrmStage, type VrmStage as VrmStageHandle } from "../character/vrm/driver";
import { pickImportedIdleMotion } from "../character/vrm/motions";
import { loadMotionTracks } from "../character/vrm/motionLoader";
import { MOTIONS_CHANGED, motionsApi, type MotionEntry } from "../api/motionsClient";
import { lerpGaze, normalizeGaze, type GazeTarget, type StageRect } from "../character/gaze";
import {
  MOUTH_CLOSED,
  onDelta,
  stepMouth,
  volumeToOpen,
  type MouthState,
} from "../character/mouth";
import { ttsPlayer } from "../character/ttsPlayer";
import { getCursor, reportCursor } from "../passthrough/cursorTracker";
import {
  LOCOMOTION_STAY_MS,
  approachLerp,
  locomotionPose,
  locomotionTransform,
  type LocomotionPose,
} from "../character/locomotion";
import {
  createDirectorState,
  submitCue,
  tickDirector,
  activeOn,
  type DirectorContext,
  type DirectorCue,
  type DirectorState,
} from "../character/actionDirector";
import {
  buildCue,
  isRepeatTap,
  toolReflexCues,
  IDLE_ROTATION_INTERVAL_MS,
  TAP_WINDOW_MS,
  HOLD_THRESHOLD_MS,
} from "../character/reflexRules";
import {
  beginSpeech,
  createCueScheduler,
  dueCues as dueReplyCues,
  endSpeech,
  resetCues as resetReplyCues,
  submitCue as scheduleReplyCue,
  type CueConverter,
} from "../cue/cueScheduler";
import {
  createSampleWindow,
  decorationsPaused,
  effectiveFps,
  nextFpsLevel,
  type FpsLevel,
} from "../character/powerGuard";
import { useConversation } from "../store/conversation";
import { devHook } from "./CharacterStage";
import { useTTSState } from "../hooks/useTTS";
import { useSettings } from "../store/settings";
import { CharacterBadge } from "./CharacterBadge";

interface VrmStageProps {
  skin: { id: string; resourceBaseUrl: string; modelFile?: string } | null;
  onActivate?: () => void;
  onContextMenu?: (x: number, y: number) => void;
  onModelReady?: (modelWidth: number, modelHeight: number) => void;
  onFallback?: () => void;
  onHitTestReady?: (hit: ((x: number, y: number) => boolean) | null) => void;
}

export function VrmStage({
  skin,
  onActivate,
  onContextMenu,
  onModelReady,
  onFallback,
  onHitTestReady,
}: VrmStageProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<VrmStageHandle | null>(null);
  const previousStageRef = useRef<VrmStageHandle | null>(null);
  const mouthRef = useRef<MouthState>(MOUTH_CLOSED);
  const gazeTargetRef = useRef<GazeTarget>({ x: 0, y: 0 });
  const gazeCurrentRef = useRef<GazeTarget>({ x: 0, y: 0 });
  const [locomotion, setLocomotion] = useState<LocomotionActionId>("come_back");
  const locomotionRef = useRef<LocomotionActionId>("come_back");
  locomotionRef.current = locomotion;
  const locomotionSinceRef = useRef(0);
  const [questionMark, setQuestionMark] = useState(false);
  const questionMarkTimerRef = useRef<number | null>(null);
  const locomotionPoseRef = useRef<LocomotionPose>({
    dx: 0,
    dy: 0,
    scale: 1,
    bodyZ: 0,
    headZ: 0,
    bodyY: 0,
    headY: 0,
  });
  const modelAspectRef = useRef(1);
  const stageRectRef = useRef<{ rect: StageRect; at: number } | null>(null);
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);
  const powerLevelRef = useRef<FpsLevel>(0);

  const characterState = useConversation((s) => s.characterState);
  const ttsPlaying = useTTSState((s) => s.playing);
  const effectiveState = ttsPlaying ? "talking" : characterState;
  const emotion = useConversation((s) => s.emotion);
  const lastTextDeltaAt = useConversation((s) => s.lastTextDeltaAt);
  const lastTextDelta = useConversation((s) => s.lastTextDelta);
  const pendingCues = useConversation((s) => s.pendingCues);
  const speechText = useTTSState((s) => s.speechText);
  const speechStartedAt = useTTSState((s) => s.speechStartedAt);
  const speechDurationMs = useTTSState((s) => s.speechDurationMs);
  const powerSave = useSettings((s) => s.powerSave);

  // ------------------------------------------------------------------
  // Action Director（与 CharacterStage 同构：本地反射 + one-shot 调度）
  // ------------------------------------------------------------------
  const toolCalls = useConversation((s) => s.toolCalls);
  const directorRef = useRef<DirectorState>(createDirectorState());
  const directorCtxRef = useRef<DirectorContext>({
    state: "idle",
    speaking: false,
    dragging: false,
    decorationsPaused: false,
  });
  const tapsRef = useRef<number[]>([]);
  const holdTimerRef = useRef<number | null>(null);
  const holdActiveAtRef = useRef<number | null>(null);
  const toolStatusRef = useRef<Map<string, string>>(new Map());
  const skinRef = useRef(skin);
  skinRef.current = skin;
  const bodyHandledRef = useRef<string | null>(null);
  const actionRequestRef = useRef(0);
  const cueSchedulerRef = useRef(createCueScheduler());
  const activeRunId = useConversation((s) => s.activeRunId);
  const prevRunIdRef = useRef<string | null>(null);
  /** 用户动作库（面板增删改）：低频轮询刷新（30s；面板与主窗口是独立 webview） */
  const userMotionsRef = useRef<Map<string, MotionEntry>>(new Map());
  const idleRequestRef = useRef(0);
  const idleKeyRef = useRef<string | null>(null);
  const syncImportedIdle = (stage: VrmStageHandle, force = false) => {
    const entry = userMotionsRef.current.get("idle_neutral");
    const key = entry ? `${entry.file}:${entry.createdAt}` : "";
    if (!force && key === idleKeyRef.current) return;
    idleKeyRef.current = key;
    const request = ++idleRequestRef.current;
    if (!entry) {
      stage.driver.setIdleMotion(null);
      return;
    }
    void loadMotionTracks(motionsApi.motionFileUrl(entry))
      .then((tracks) => {
        if (stageRef.current === stage && idleRequestRef.current === request)
          stage.driver.setIdleMotion(tracks);
      })
      .catch((err) => {
        if (stageRef.current !== stage || idleRequestRef.current !== request) return;
        console.warn("[mochi] 导入待机加载失败：", err);
        idleKeyRef.current = null;
        stage.driver.setIdleMotion(null);
      });
  };
  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      motionsApi
        .listMotions(skin?.id)
        .then((list) => {
          if (cancelled) return;
          userMotionsRef.current = new Map(list.map((e) => [e.id, e]));
          const stage = stageRef.current;
          if (stage) syncImportedIdle(stage);
        })
        .catch(() => undefined); // 动作库不可达时保持静态站姿
    };
    refresh();
    const timer = window.setInterval(refresh, 30_000);
    window.addEventListener(MOTIONS_CHANGED, refresh);
    window.addEventListener("focus", refresh);
    const channel =
      typeof BroadcastChannel !== "undefined" ? new BroadcastChannel(MOTIONS_CHANGED) : null;
    if (channel) channel.onmessage = refresh;
    return () => {
      cancelled = true;
      idleRequestRef.current += 1;
      window.clearInterval(timer);
      window.removeEventListener(MOTIONS_CHANGED, refresh);
      window.removeEventListener("focus", refresh);
      channel?.close();
    };
  }, [skin?.id]);

  /** 语义动作解析 + 播放：导入动作库（含 ext.*）；idle_neutral/
   *  未注册 → 停表演回 stance。用户资产经加载器汇合（vrma/glb/fbx）。 */
  const playResolvedAction = (actionId: string): boolean => {
    const stage = stageRef.current;
    if (!stage) return false;
    const request = ++actionRequestRef.current;
    const isCurrent = () => stageRef.current === stage && actionRequestRef.current === request;
    if (actionId === "idle_neutral") {
      stage.driver.stopAction();
      return true;
    }
    const userEntry = userMotionsRef.current.get(actionId);
    if (userEntry) {
      void loadMotionTracks(motionsApi.motionFileUrl(userEntry))
        .then((tracks) => {
          if (!isCurrent()) return;
          stage.driver.playAction(
            {
              id: userEntry.id,
              label: userEntry.label,
              kind: userEntry.kind,
              durationMs: userEntry.durationMs,
              priority: userEntry.priority,
              cooldownMs: userEntry.cooldownMs,
              agentSelectable: userEntry.agentSelectable,
              tags: userEntry.tags,
            },
            tracks,
          );
        })
        .catch((err) => {
          if (!isCurrent()) return;
          console.warn(`[mochi] 导入动作 ${actionId} 加载失败：`, err);
          stage.driver.stopAction();
        });
      return true;
    }
    stage.driver.stopAction(); // idle_neutral / 未注册
    return false;
  };

  directorCtxRef.current = {
    state: ttsPlaying ? "talking" : characterState,
    speaking: ttsPlaying,
    dragging: holdActiveAtRef.current !== null && Date.now() - holdActiveAtRef.current < 2000,
    decorationsPaused: decorationsPaused(powerLevelRef.current),
  };

  useEffect(() => {
    if (import.meta.env.DEV) {
      (window as unknown as { __mochiDirector?: typeof devHook }).__mochiDirector = devHook;
    }
  }, []);

  useEffect(() => {
    if (activeRunId !== null && activeRunId !== prevRunIdRef.current) {
      resetReplyCues(cueSchedulerRef.current);
    }
    prevRunIdRef.current = activeRunId;
  }, [activeRunId]);

  const consumePendingCues = useConversation((s) => s.consumePendingCues);
  useEffect(() => {
    if (pendingCues.length === 0) return;
    if (import.meta.env.DEV) console.debug(`[vrm] 排水 pendingCues=${pendingCues.length}`);
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

  // 自动回位（与 Live2D 路径同语义）
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

  const cueConvertRef = useRef<CueConverter>(() => null);
  cueConvertRef.current = (proto, channel, now) => {
    const actionId =
      channel === "face"
        ? (proto.channels.face?.emotion ?? "neutral")
        : (proto.channels.body?.actionId ?? "idle_neutral");
    if (channel === "body" && actionId !== "idle_neutral" && !userMotionsRef.current.has(actionId))
      return null;
    const base = buildCue(actionId, {
      channel,
      source: proto.source,
      now,
      actions: undefined, // VRM 仅使用导入动作库的调度参数
      durationMs: channel === "body" ? userMotionsRef.current.get(actionId)?.durationMs : undefined,
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

  const submitReflexes = useCallback((cues: DirectorCue[]) => {
    const ctx = directorCtxRef.current;
    for (const cue of cues) {
      if (
        cue.channel === "body" &&
        cue.actionId !== "idle_neutral" &&
        !userMotionsRef.current.has(cue.actionId)
      )
        continue;
      const motion = cue.channel === "body" ? userMotionsRef.current.get(cue.actionId) : undefined;
      const resolved = motion
        ? { ...cue, durationMs: motion.durationMs, cooldownMs: motion.cooldownMs }
        : cue;
      const verdict = submitCue(directorRef.current, resolved, ctx, Date.now());
      if (import.meta.env.DEV) {
        console.debug(
          `[director] ${verdict.accepted ? "accept" : "reject"}(${verdict.accepted ? "" : verdict.reason}) ${cue.channel}:${cue.actionId} pri=${cue.priority}`,
        );
      }
    }
  }, []);

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
    const cues = toolReflexCues(latest.status as "running" | "success" | "error" | "denied", {
      now: latest.at,
      actions: undefined,
    });
    if (cues.length > 0) submitReflexes(cues);
  }, [toolCalls, submitReflexes]);

  // ------------------------------------------------------------------
  // 舞台生命周期：加载 / 换肤不闪白 / 降级
  // ------------------------------------------------------------------
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !skin) return;
    setFailed(false);
    let cancelled = false;
    const url = `${skin.resourceBaseUrl}/${skin.modelFile ?? ""}`;

    loadVrmStage(container, url)
      .then((loaded) => {
        if (cancelled) {
          loaded.dispose();
          return;
        }
        stageRef.current = loaded;
        syncImportedIdle(loaded, true);
        if (previousStageRef.current) {
          previousStageRef.current.dispose();
          previousStageRef.current = null;
        }
        console.info(`[mochi] character-ready(vrm) +${Math.round(performance.now())}ms`);
        onModelReady?.(loaded.modelWidth, loaded.modelHeight);
        modelAspectRef.current = loaded.modelWidth / loaded.modelHeight;
        setReady(true);
      })
      .catch((err) => {
        console.error("[VrmStage] 模型加载失败，降级为占位形象：", err);
        if (!cancelled) {
          setFailed(true);
          onFallback?.();
        }
      });

    return () => {
      cancelled = true;
      actionRequestRef.current += 1;
      // 换肤不闪白（ADR-0006 D10）：旧舞台转存，新舞台就绪后才销毁；
      // 彻底卸载由 unmount effect 收口
      if (stageRef.current) previousStageRef.current = stageRef.current;
      stageRef.current = null;
      setReady(false);
    };
  }, [skin?.id, skin?.resourceBaseUrl, skin?.modelFile, onModelReady, onFallback]);

  useEffect(
    () => () => {
      stageRef.current?.dispose();
      previousStageRef.current?.dispose();
      stageRef.current = null;
      previousStageRef.current = null;
    },
    [],
  );

  // 命中判定（Raycaster 几何；掩码不需要）+ 穿透接线
  useEffect(() => {
    const hitTest = (x: number, y: number) => {
      const stage = stageRef.current;
      if (!stage) return true; // 未就绪/降级：保持旧行为（整窗可交互）
      return stage.driver.hitTestAt(x, y).length > 0;
    };
    onHitTestReady?.((x, y) => hitTest(x, y));
    return () => {
      onHitTestReady?.(null);
    };
  }, [onHitTestReady]);

  // 状态机：(有效状态, 情绪) → 驱动基调
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage || !ready || !skin) return;
    stage.driver.applyState(effectiveState, emotion);
  }, [effectiveState, emotion, ready, skin]);

  // 口型 delta 驱动
  useEffect(() => {
    if (lastTextDeltaAt > 0) {
      mouthRef.current = onDelta(mouthRef.current, lastTextDelta);
    }
  }, [lastTextDeltaAt, lastTextDelta]);

  // 光标上报（与 Live2D 路径一致）
  useEffect(() => {
    if (!ready) return;
    const onMove = (e: MouseEvent) => reportCursor(e.clientX, e.clientY);
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [ready]);

  // ------------------------------------------------------------------
  // 调度推进主循环（独立 rAF）：director 结算 + cue 排水 + 幂等消费 +
  // 口型/视线/face 覆写/locomotion 姿态 + powerGuard 帧采样
  // ------------------------------------------------------------------
  useEffect(() => {
    if (!ready) return;
    const sampleWindow = createSampleWindow();
    let lastNow: number | null = null;
    let evaluateAccum = 0;
    let raf = 0;

    const stageGazeTarget = (): GazeTarget => {
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
    };

    const loop = () => {
      raf = requestAnimationFrame(loop);
      const stage = stageRef.current;
      if (!stage) return;
      const nowMs = performance.now();
      const deltaMs = lastNow === null ? 16 : Math.min(100, nowMs - lastNow);
      lastNow = nowMs;
      sampleWindow.push(deltaMs, nowMs);
      evaluateAccum += deltaMs;
      if (evaluateAccum >= 1000) {
        const avg = sampleWindow.average();
        const next = nextFpsLevel(powerLevelRef.current, avg, powerSave);
        if (next !== powerLevelRef.current) {
          powerLevelRef.current = next;
          stage.driver.setFps(effectiveFps(30, next));
        }
        evaluateAccum = 0;
      }

      const driver = stage.driver;
      const now = Date.now();
      tickDirector(directorRef.current, directorCtxRef.current, now);
      for (const c of dueReplyCues(cueSchedulerRef.current, now, cueConvertRef.current)) {
        const verdict = submitCue(directorRef.current, c, directorCtxRef.current, now);
        if (import.meta.env.DEV) {
          console.debug(
            `[vrm] dueCue ${c.actionId}:${c.channel} -> ${verdict.accepted ? "accept" : `reject(${verdict.reason})`}`,
          );
        }
        devHook.lastReplyCue = { actionId: c.actionId, channel: c.channel, at: now };
      }

      const bodyAction = activeOn(directorRef.current, "body");
      if (bodyAction === null && bodyHandledRef.current !== null) {
        bodyHandledRef.current = null;
        actionRequestRef.current += 1;
        driver.stopAction();
      }
      if (bodyAction !== null && bodyHandledRef.current !== bodyAction.cue.cueId) {
        bodyHandledRef.current = bodyAction.cue.cueId;
        const actionId = bodyAction.cue.actionId;
        const userEntry = userMotionsRef.current.get(actionId);
        const def = userEntry ?? null;
        playResolvedAction(actionId);
        devHook.lastPlayMotion = { group: actionId, at: Date.now() };
        // 问号贴图（H4）：question 动作同期头顶浮出「？」
        if (def?.id === "question") {
          setQuestionMark(true);
          if (questionMarkTimerRef.current !== null) {
            window.clearTimeout(questionMarkTimerRef.current);
          }
          questionMarkTimerRef.current = window.setTimeout(
            () => setQuestionMark(false),
            def.durationMs,
          );
        }
      }

      // 口型：TTS 音量优先，delta 节奏兜底
      if (ttsPlaying) {
        driver.setMouthOpen(volumeToOpen(ttsPlayer.level()));
        mouthRef.current = MOUTH_CLOSED;
      } else {
        mouthRef.current = stepMouth(mouthRef.current, deltaMs);
        driver.setMouthOpen(mouthRef.current.open);
      }

      // 视线（talking/idle 启用；VRM sleeping/error 由 applyState 情绪基调处理）
      gazeTargetRef.current = stageGazeTarget();
      gazeCurrentRef.current = lerpGaze(gazeCurrentRef.current, gazeTargetRef.current);
      driver.setGaze(gazeCurrentRef.current.x, gazeCurrentRef.current.y);

      // face 通道覆写：one-shot 期间写，结束回落
      const face = activeOn(directorRef.current, "face");
      driver.setFaceOverride(face !== null ? face.cue.actionId : null);

      // locomotion 姿态趋近（度）+ 容器 CSS 位移（P0 沿用 2D 方案，P3 场景化）
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
        driver.setPosture({
          bodyZ: cur.bodyZ,
          headZ: cur.headZ,
          bodyY: cur.bodyY,
          headY: cur.headY,
        });
      }
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [ready, ttsPlaying, powerSave]);

  // 闲置轮换池（与 Live2D 路径同构）
  const idleSinceRef = useRef(Date.now());
  useEffect(() => {
    if (!ready) return;
    const timer = window.setInterval(() => {
      const now = Date.now();
      if (effectiveState !== "idle") {
        idleSinceRef.current = now;
        return;
      }
      if (now - idleSinceRef.current < IDLE_ROTATION_INTERVAL_MS) return;
      const motion = pickImportedIdleMotion([...userMotionsRef.current.values()], Math.random());
      if (!motion) return;
      const actionId = motion.id;
      idleSinceRef.current = now - 60_000;
      submitReflexes([
        buildCue(actionId, { channel: "body", source: "proactive", now, actions: undefined }),
      ]);
    }, IDLE_ROTATION_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [ready, effectiveState, submitReflexes]);

  // ------------------------------------------------------------------
  // 交互（语义与 Live2D 路径一致：命中才交互；tap/长按/拖拽反射）
  // ------------------------------------------------------------------
  const hitTestNow = (x: number, y: number) => {
    const stage = stageRef.current;
    if (!stage) return false;
    return stage.driver.hitTestAt(x, y).length > 0;
  };
  const handleClick = (e: ReactMouseEvent) => {
    if (e.button !== 0) return;
    if (!hitTestNow(e.clientX, e.clientY)) return;
    const nowMs = Date.now();
    tapsRef.current = [...tapsRef.current.filter((t) => nowMs - t <= TAP_WINDOW_MS), nowMs];
    if (isRepeatTap(tapsRef.current, nowMs)) {
      submitReflexes([
        buildCue("surprised", {
          channel: "body",
          source: "reflex",
          now: nowMs,
          actions: undefined,
        }),
      ]);
    } else {
      submitReflexes([
        buildCue("nod", { channel: "body", source: "reflex", now: nowMs, actions: undefined }),
      ]);
    }
    onActivate?.();
  };
  const handlePointerDown = (e: ReactMouseEvent) => {
    if (e.button !== 0) return;
    if (!hitTestNow(e.clientX, e.clientY)) return;
    if (holdTimerRef.current === null) {
      holdTimerRef.current = window.setTimeout(() => {
        holdTimerRef.current = null;
        holdActiveAtRef.current = Date.now();
        stageRef.current?.driver.resetSprings();
        submitReflexes([
          buildCue("surprised", {
            channel: "body",
            source: "reflex",
            now: Date.now(),
            actions: undefined,
            priority: 80,
          }),
        ]);
      }, HOLD_THRESHOLD_MS);
    }
    if ("__TAURI_INTERNALS__" in window) void getCurrentWindow().startDragging();
  };
  const handlePointerUp = () => {
    if (holdTimerRef.current !== null) {
      window.clearTimeout(holdTimerRef.current);
      holdTimerRef.current = null;
    }
    if (holdActiveAtRef.current !== null) {
      holdActiveAtRef.current = null;
      submitReflexes([
        buildCue("idle_neutral", {
          channel: "body",
          source: "reflex",
          now: Date.now(),
          actions: undefined,
          priority: 80,
        }),
      ]);
    }
  };
  const handleContextMenu = (e: ReactMouseEvent) => {
    e.preventDefault();
    onContextMenu?.(e.clientX, e.clientY);
  };

  const activePose = locomotionPoseRef.current;
  const transformed = activePose.dx !== 0 || activePose.dy !== 0 || activePose.scale !== 1;
  return (
    <div
      className={`character-stage${failed ? " character-stage--failed" : ""}${transformed ? " character-stage--locomoted" : ""}`}
      ref={containerRef}
      data-skin={skin?.id}
      data-locomotion={locomotion}
      data-engine="vrm"
      style={transformed ? { transform: locomotionTransform(activePose) } : undefined}
      onClick={handleClick}
      onContextMenu={handleContextMenu}
      onPointerDown={handlePointerDown}
      onPointerUp={handlePointerUp}
    >
      {questionMark ? (
        <div className="character-qmark" aria-hidden="true">
          ？
        </div>
      ) : null}
      {failed ? <CharacterBadge /> : null}
    </div>
  );
}
