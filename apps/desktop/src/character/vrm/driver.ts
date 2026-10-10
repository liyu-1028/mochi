/**
 * VRM 渲染驱动（ADR-0011 D2/D3）：Three.js + @pixiv/three-vrm。
 *
 * 四层合成（单 AnimationMixer）：
 * - L0 姿态基底：静态自然站姿，或用户导入的待机 VRMA；
 * - L2 表演：导入的 VRMA 动作，crossfade 进出（约 0.2s）后回落 L0；
 * - L3 颜值：expressionManager（情绪基调 + face 覆写 + 程序化眨眼）+ lookAt
 *   视线 + 口型（aa），独立于骨骼层叠加。
 *
 * 与 Live2D driver 的关系：并行实现（D8 双栈），不共享 CharacterDriver 接口——
 * P1 观感 gate 后 Live2D 拆除时再统一收敛。
 *
 * 待机资产经 normalized 骨架重定向；换模型/调动作前仍需验证姿态和取景。
 */
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils, VRMHumanBoneName, type VRM } from "@pixiv/three-vrm";
import type { CharacterState, Emotion } from "@mochi/protocol";
import { createVrmWorld, type VrmViewOptions } from "./world";
import { loadMotionTracks, type VrmTracks } from "./motionLoader";
import type { VrmMotionDef } from "./motions";

/** 逻辑像素/米：布局倒置的桥（computeCharacterLayout 吃逻辑像素尺寸） */
export const PIXELS_PER_METER = 900;

/** crossfade 时长（ms）：L2 进出 stance */
const FADE_MS = 220;

/** 情绪 → VRM 标准 preset 映射（模型缺 preset 时自动跳过，fallback neutral 零表情） */
const EMOTION_PRESET: Record<Emotion, { preset: string; weight: number }> = {
  neutral: { preset: "", weight: 0 },
  happy: { preset: "happy", weight: 0.75 },
  sad: { preset: "sad", weight: 0.7 },
  confused: { preset: "", weight: 0 }, // VRM 无标准 confused；由姿态层表意（P1 细化）
  surprised: { preset: "surprised", weight: 0.8 },
  embarrassed: { preset: "", weight: 0 },
  angry: { preset: "angry", weight: 0.65 },
};

/** face 通道反射专用（非词表情绪，与 Live2D FACE_REFLEX_PRESETS 对位） */
const FACE_REFLEX_PRESET: Record<string, { preset: string; weight: number }> = {
  worried: { preset: "sad", weight: 0.35 },
};

export interface PostureAngles {
  bodyZ: number;
  headZ: number;
  bodyY: number;
  headY: number;
}

export interface VrmDriver {
  readonly kind: "vrm";
  /** 状态基调（6 状态机 + 情绪 → L0/L3 参数） */
  applyState(state: CharacterState, emotion: Emotion | null): void;
  /** 播放 one-shot 动作（L2）：内部含资产加载，异步完成前保持当前姿态 */
  playAction(def: VrmMotionDef, tracks?: VrmTracks): void;
  /** face 通道覆写：情绪名或反射名；null = 回落状态基调 */
  setFaceOverride(face: string | null): void;
  setMouthOpen(open: number): void;
  setGaze(nx: number, ny: number): void;
  setPosture(partial: Partial<PostureAngles>): void;
  /** 命中分区（视口坐标 → Raycaster → Head/Body；语义对齐 Live2D hitTestAt） */
  hitTestAt(clientX: number, clientY: number): string[];
  setFps(fps: number): void;
  /** 停止当前表演动作（idle_neutral 语义：crossfade 回 L0 基底） */
  stopAction(): void;
  /** 触发一次 springbone 复位（位移/seek 后，防姿态抽搐） */
  resetSprings(): void;
  /** Imported idle_neutral becomes the looping base; null restores static rest. */
  setIdleMotion(tracks: VrmTracks | null): void;
}

export interface VrmStage {
  driver: VrmDriver;
  /** 模型逻辑尺寸（米 × PIXELS_PER_METER），onModelReady 布局用 */
  modelWidth: number;
  modelHeight: number;
  setRunning(running: boolean): void;
  resetView(): void;
  dispose(): void;
}

/** 中间轨道 → 目标模型 clip：轨道重命名到 normalized 骨骼 + hips 等比缩放 */
export function tracksToClip(
  tracks: VrmTracks,
  vrm: VRM,
  name: string,
): THREE.AnimationClip | null {
  const humanoid = vrm.humanoid;
  const out: THREE.KeyframeTrack[] = [];
  for (const [bone, track] of tracks.rotation) {
    const node = humanoid.getNormalizedBoneNode(bone);
    if (!node) continue;
    out.push(
      new THREE.QuaternionKeyframeTrack(
        `${node.name}.quaternion`,
        track.times,
        track.values.slice(),
      ),
    );
  }
  if (tracks.hipsTranslation) {
    const hips = humanoid.getNormalizedBoneNode("hips");
    const restY = humanoid.normalizedRestPose.hips?.position?.[1] ?? 0.92;
    const firstY = tracks.hipsTranslation.values[1];
    if (hips && firstY) {
      const scale = restY / firstY;
      // x/z 水平位移保留（脚步走位），y 缩放到目标髋高
      const values = tracks.hipsTranslation.values.map((v, i) => v * (i % 3 === 1 ? scale : 1));
      out.push(
        new THREE.VectorKeyframeTrack(
          `${hips.name}.position`,
          tracks.hipsTranslation.times,
          values,
        ),
      );
    }
  }
  const em = vrm.expressionManager;
  if (em) {
    for (const [expressionName, track] of tracks.expressions) {
      const trackName = em.getExpressionTrackName(expressionName);
      if (trackName) {
        out.push(new THREE.NumberKeyframeTrack(trackName, track.times, track.values.slice()));
      }
    }
  }
  if (out.length === 0) return null;
  return new THREE.AnimationClip(name, tracks.duration, out);
}

/** Static relaxed rest pose; no animation asset, breathing or authored gesture is bundled. */
function makeRestClip(vrm: VRM): THREE.AnimationClip {
  const tracks: THREE.KeyframeTrack[] = [];
  for (const bone of Object.values(VRMHumanBoneName)) {
    const node = vrm.humanoid.getNormalizedBoneNode(bone);
    if (!node) continue;
    const q = node.quaternion.clone();
    if (bone === "leftUpperArm" || bone === "rightUpperArm") {
      q.setFromEuler(new THREE.Euler(0, 0, bone === "leftUpperArm" ? -1.35 : 1.35));
    } else if (bone === "leftLowerArm" || bone === "rightLowerArm") {
      q.setFromEuler(new THREE.Euler(0.12, 0, 0));
    }
    tracks.push(
      new THREE.QuaternionKeyframeTrack(
        `${node.name}.quaternion`,
        [0, 1],
        [...q.toArray(), ...q.toArray()],
      ),
    );
    if (bone === "hips") {
      tracks.push(
        new THREE.VectorKeyframeTrack(
          `${node.name}.position`,
          [0, 1],
          [...node.position.toArray(), ...node.position.toArray()],
        ),
      );
    }
  }
  return new THREE.AnimationClip("mochi-static-rest", 1, tracks);
}

export async function loadVrmStage(
  host: HTMLElement,
  url: string,
  options: VrmViewOptions = {},
): Promise<VrmStage> {
  const world = createVrmWorld(host, options);
  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  const gltf = await loader.loadAsync(url).catch((error: unknown) => {
    world.dispose();
    throw error;
  });
  const vrm = gltf.userData.vrm as VRM | undefined;
  if (!vrm) {
    world.dispose();
    throw new Error("资源不是可识别的 VRM 模型");
  }

  VRMUtils.removeUnnecessaryVertices(vrm.scene);
  VRMUtils.rotateVRM0(vrm);
  vrm.scene.traverse((object) => {
    object.frustumCulled = false;
  });

  const mixer = new THREE.AnimationMixer(vrm.scene);
  const restClip = makeRestClip(vrm);
  let stanceClip = restClip;
  let stanceAction = mixer.clipAction(stanceClip);
  stanceAction.setLoop(THREE.LoopRepeat, Infinity).play();
  // 测量实际站姿，不能使用未推进 mixer 的 T-pose 或蒙皮旧包围盒。
  mixer.update(0);
  vrm.update(0);

  // 校准落地：脚底贴 y=0（世界原点在脚底，布局/命中计算据此）
  vrm.scene.updateMatrixWorld(true);
  const groundBounds = new THREE.Box3().setFromObject(vrm.scene, true);
  const size = groundBounds.getSize(new THREE.Vector3());
  vrm.scene.position.y -= groundBounds.min.y;
  vrm.scene.updateMatrixWorld(true);
  groundBounds.translate(new THREE.Vector3(0, -groundBounds.min.y, 0));
  world.frame(groundBounds);

  world.scene.add(vrm.scene);

  // ------------------------------------------------------------------
  // 驱动状态
  // ------------------------------------------------------------------
  let emotionBase: Emotion | null = null;
  let faceOverride: string | null = null;
  let mouthOpen = 0;
  let blinkPhase = Math.random() * 3; // 眨眼节律（s）
  let eyesForcedClosed = false;
  let performing: { action: THREE.AnimationAction; def: VrmMotionDef } | null = null;
  let posture: PostureAngles = { bodyZ: 0, headZ: 0, bodyY: 0, headY: 0 };
  let running = true;
  let fpsCap = 60;
  let disposed = false;
  let actionRequest = 0;

  const gazeTarget = new THREE.Object3D();
  gazeTarget.position.set(0, 1.3, 3);
  if (vrm.lookAt) vrm.lookAt.target = gazeTarget;
  world.scene.add(gazeTarget);

  const em = vrm.expressionManager ?? null;
  let appliedPreset: string | null = null;
  const applyEmotionWeight = () => {
    if (!em) return;
    const source = faceOverride ?? emotionBase;
    const motionExpression = faceOverride === null ? performing?.def.expression : null;
    const mapping = motionExpression
      ? { preset: motionExpression.preset, weight: motionExpression.intensity }
      : source
        ? (EMOTION_PRESET[source as Emotion] ?? FACE_REFLEX_PRESET[source])
        : null;
    const preset = mapping?.preset || null;
    if (appliedPreset && appliedPreset !== preset) em.setValue(appliedPreset, 0);
    appliedPreset = preset;
    if (preset && mapping) em.setValue(preset, mapping.weight);
  };

  const stopPerformance = (cancelPending = true) => {
    if (cancelPending) actionRequest += 1;
    if (!performing) return;
    performing.action.fadeOut(FADE_MS / 1000);
    performing = null;
    if (stanceAction) {
      stanceAction.enabled = true;
      stanceAction.fadeIn(FADE_MS / 1000).play();
    }
  };

  const startAction = (def: VrmMotionDef, clip: THREE.AnimationClip) => {
    stopPerformance();
    // 补齐没有 authored 轨道的基底骨骼，再整体交叉淡化；否则 stance 与表演
    // 同时满权重会把旋转平均，或者关掉 stance 后未动的手臂突然回到 T-pose。
    const animated = new Set(clip.tracks.map((track) => track.name));
    for (const track of stanceClip?.tracks ?? []) {
      if (!animated.has(track.name)) clip.tracks.push(track.clone());
    }
    const action = mixer.clipAction(clip);
    action.reset();
    action.setLoop(
      def.kind === "loop" ? THREE.LoopRepeat : THREE.LoopOnce,
      def.kind === "loop" ? Infinity : 1,
    );
    action.clampWhenFinished = true;
    stanceAction?.fadeOut(FADE_MS / 1000);
    action.fadeIn(FADE_MS / 1000).play();
    performing = { action, def };
  };
  mixer.addEventListener("finished", ({ action }) => {
    if (performing?.action === action) stopPerformance(false);
  });

  // ------------------------------------------------------------------
  // 帧循环
  // ------------------------------------------------------------------
  let lastTime = performance.now();
  let accumulator = 0;
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();

  world.renderer.setAnimationLoop((now: number) => {
    const deltaMs = Math.min(Math.max(now - lastTime, 0), 100);
    lastTime = now;
    if (!running || document.hidden) return;
    accumulator += deltaMs;
    const budget = 1000 / fpsCap;
    if (accumulator < budget) return;
    const delta = accumulator / 1000;
    accumulator = 0;

    mixer.update(delta);

    // L0 姿态附加层（locomotion 倚靠姿态，度 → rad）：mixer 之后叠加
    if (posture.bodyZ || posture.headZ || posture.bodyY || posture.headY) {
      const deg = Math.PI / 180;
      const apply = (
        bone: Parameters<VRM["humanoid"]["getNormalizedBoneNode"]>[0],
        z: number,
        y: number,
      ) => {
        const node = vrm.humanoid.getNormalizedBoneNode(bone);
        if (!node) return;
        if (z)
          node.quaternion.multiply(
            new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), z * deg),
          );
        if (y)
          node.quaternion.multiply(
            new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), y * deg),
          );
      };
      apply("spine", posture.bodyZ, posture.bodyY);
      apply("head", posture.headZ, posture.headY);
    }

    // L3：眨眼节律（2.4–4.8s 一次，0.14s 合眼）+ 口型 + 情绪基调
    blinkPhase += delta;
    const cycle = 3.6;
    const t = blinkPhase % cycle;
    if (em && !eyesForcedClosed) {
      const blinkWindow = 0.14;
      const blinkStart = cycle - 0.9;
      em.setValue(
        "blink",
        t > blinkStart && t < blinkStart + blinkWindow
          ? Math.sin(((t - blinkStart) / blinkWindow) * Math.PI)
          : 0,
      );
    } else if (em && eyesForcedClosed) {
      em.setValue("blink", 1);
    }
    if (em) {
      em.setValue("aa", Math.min(1, Math.max(0, mouthOpen)));
      applyEmotionWeight();
    }

    vrm.update(delta);
    world.updateView();
    world.renderer.render(world.scene, world.camera);
  });

  const driver: VrmDriver = {
    kind: "vrm",

    applyState(state, emotion) {
      emotionBase = emotion;
      eyesForcedClosed = state === "sleeping";
      if (state !== "idle") stopPerformance();
    },

    playAction(def, tracks) {
      const request = ++actionRequest;
      const run = (clip: THREE.AnimationClip | null) => {
        if (!clip || disposed || request !== actionRequest) return;
        startAction(def, clip);
      };
      if (tracks) {
        run(tracksToClip(tracks, vrm, `mochi-${def.id}`));
        return;
      }
      if (!def.assetUrl) return;
      // Imported VRMA assets are the only source of performed motion.
      void loadMotionTracks(def.assetUrl)
        .then((loaded) => {
          run(tracksToClip(loaded, vrm, `mochi-${def.id}`));
        })
        .catch((error: unknown) => {
          if (!disposed) console.warn(`[mochi] 动作 ${def.id} 加载失败：`, error);
        });
    },

    setFaceOverride(face) {
      faceOverride = face;
    },

    setMouthOpen(open) {
      mouthOpen = open;
    },

    setGaze(nx, ny) {
      // 归一化 [-1,1] → 头前 2m 平面目标；y 以头部基准高度为中心
      gazeTarget.position.set(nx * 2.2, 1.25 + ny * 1.4, 2.5);
    },

    setPosture(partial) {
      posture = { ...posture, ...partial };
    },

    hitTestAt(clientX, clientY) {
      const canvas = world.renderer.domElement;
      const rect = canvas.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return [];
      ndc.set(
        ((clientX - rect.left) / rect.width) * 2 - 1,
        -((clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(ndc, world.camera);
      const hits = raycaster.intersectObject(vrm.scene, true);
      const hit = hits.find((h) => h.object instanceof THREE.Mesh);
      if (!hit) return [];
      // 头/身分区：VRM1 firstPerson 标注（头部网格 firstPersonOnly/auto）
      const annotations = vrm.firstPerson?.meshAnnotations ?? [];
      const hitMesh = hit.object;
      const isHead = annotations.some(
        (a) =>
          (a.type === "firstPersonOnly" || a.type === "auto") &&
          a.meshes.some((m) => m === hitMesh || m.uuid === hitMesh.uuid),
      );
      if (isHead) return ["Head"];
      return ["Body"];
    },

    setFps(fps) {
      fpsCap = fps;
    },

    stopAction() {
      stopPerformance();
    },

    setIdleMotion(tracks) {
      stopPerformance();
      stanceAction.stop();
      mixer.uncacheAction(stanceClip);
      stanceClip = tracks ? (tracksToClip(tracks, vrm, "imported-idle") ?? restClip) : restClip;
      const animated = new Set(stanceClip.tracks.map((track) => track.name));
      for (const track of restClip.tracks) {
        if (!animated.has(track.name)) stanceClip.tracks.push(track.clone());
      }
      stanceAction = mixer.clipAction(stanceClip);
      stanceAction.reset().setLoop(THREE.LoopRepeat, Infinity).play();
      mixer.update(0);
      vrm.update(0);
    },

    resetSprings() {
      vrm.springBoneManager?.reset();
    },
  };

  console.info(
    `[mochi] vrm-stage size=${size.x.toFixed(2)}x${size.y.toFixed(2)}m expressions=${em?.expressions.length ?? 0}`,
  );

  return {
    driver,
    modelWidth: Math.round(size.x * PIXELS_PER_METER),
    modelHeight: Math.round(size.y * PIXELS_PER_METER),
    setRunning(next: boolean) {
      running = next;
    },
    resetView: world.resetView,
    dispose() {
      if (disposed) return;
      disposed = true;
      actionRequest += 1;
      running = false;
      world.renderer.setAnimationLoop(null);
      mixer.stopAllAction();
      mixer.uncacheRoot(vrm.scene);
      VRMUtils.deepDispose(vrm.scene);
      world.dispose();
    },
  };
}
