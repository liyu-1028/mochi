import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import {
  BUBBLE_HEADROOM,
  TARGET_CHARACTER_HEIGHT,
  VRM_TOP_HEADROOM_RATIO,
} from "../../layout/characterLayout";
import { loadVrmStage } from "./driver";
import type { VRMHumanBoneName } from "@pixiv/three-vrm";
import type { VrmMotionDef } from "./motions";

const mocks = vi.hoisted(() => ({
  load: vi.fn(),
  motionLoad: vi.fn(),
  render: vi.fn(),
  dispose: vi.fn(),
  remove: vi.fn(),
  loop: null as ((now: number) => void) | null,
  resize: null as (() => void) | null,
}));

vi.mock("three", async (importOriginal) => ({
  ...(await importOriginal<typeof import("three")>()),
  WebGLRenderer: class {
    domElement = { style: {}, setAttribute: vi.fn(), remove: mocks.remove };
    setClearColor() {}
    setPixelRatio() {}
    setSize() {}
    setAnimationLoop(fn: typeof mocks.loop) {
      mocks.loop = fn;
    }
    render = mocks.render;
    dispose = mocks.dispose;
  },
}));
vi.mock("three/addons/loaders/GLTFLoader.js", () => ({
  GLTFLoader: class {
    register() {}
    loadAsync = mocks.load;
  },
}));
vi.mock("./motionLoader", () => ({ loadMotionTracks: mocks.motionLoad }));

function idleTracks() {
  const rotation = new Map<VRMHumanBoneName, THREE.QuaternionKeyframeTrack>();
  for (const side of ["left", "right"] as const) {
    const upper = side === "left" ? -1.45 : 1.45;
    for (const [part, keys] of [
      [
        "Shoulder",
        [
          [0, 0, 0],
          [0, 0, 0],
          [0, 0, 0],
        ],
      ],
      [
        "UpperArm",
        [
          [0, 0, upper],
          [0, 0, upper],
          [0, 0, upper],
        ],
      ],
      [
        "LowerArm",
        [
          [0.2, 0, 0],
          [0.28, 0, 0],
          [0.2, 0, 0],
        ],
      ],
      [
        "Hand",
        [
          [0.1, 0, 0],
          [0.1, 0, 0],
          [0.1, 0, 0],
        ],
      ],
    ] as const) {
      const values = keys.flatMap(([x, y, z]) =>
        new THREE.Quaternion().setFromEuler(new THREE.Euler(x, y, z)).toArray(),
      );
      const name = `${side}${part}` as const;
      rotation.set(
        name,
        new THREE.QuaternionKeyframeTrack(`${name}.quaternion`, [0, 1, 2], values),
      );
    }
  }
  return { duration: 2, rotation, hipsTranslation: null, expressions: new Map() };
}

function fixture() {
  const scene = new THREE.Group();
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(0.65, 1.7, 0.2));
  mesh.position.y = 0.85;
  scene.add(mesh);
  const bones = new Map(
    [
      "spine",
      "head",
      "leftShoulder",
      "leftUpperArm",
      "leftLowerArm",
      "leftHand",
      "rightShoulder",
      "rightUpperArm",
      "rightLowerArm",
      "rightHand",
    ].map((name) => {
      const node = new THREE.Object3D();
      node.name = name;
      scene.add(node);
      return [name, node];
    }),
  );
  const weights = new Map<string, number>();
  const vrm = {
    scene,
    meta: { metaVersion: "1" },
    humanoid: { getNormalizedBoneNode: (name: string) => bones.get(name), normalizedRestPose: {} },
    expressionManager: {
      expressions: [],
      setValue: (name: string, weight: number) =>
        weights.set(name, THREE.MathUtils.clamp(weight, 0, 1)),
      getExpressionTrackName: () => null,
    },
    update: vi.fn(),
  };
  mocks.load.mockResolvedValue({ userData: { vrm } });
  const host = {
    clientWidth: 304,
    clientHeight: BUBBLE_HEADROOM + TARGET_CHARACTER_HEIGHT * (1 + VRM_TOP_HEADROOM_RATIO),
    appendChild: vi.fn(),
  };
  const frame = (ms = 100) => {
    now += ms;
    mocks.loop?.(now);
    const camera = mocks.render.mock.lastCall?.[1] as THREE.OrthographicCamera;
    camera?.updateMatrixWorld(true);
    return camera;
  };
  return { host: host as unknown as HTMLElement, frame, bones, weights };
}

let now = 0;
beforeEach(() => {
  vi.clearAllMocks();
  mocks.motionLoad.mockReset().mockResolvedValue(idleTracks());
  now = 0;
  vi.spyOn(performance, "now").mockReturnValue(0);
  let seed = 1;
  vi.spyOn(Math, "random").mockImplementation(() => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 2 ** 32;
  });
  vi.stubGlobal("window", { devicePixelRatio: 1 });
  vi.stubGlobal("document", { hidden: false });
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        mocks.resize = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("VRM stage rendering", () => {
  const motion: VrmMotionDef = {
    id: "test-motion",
    label: "test",
    kind: "oneshot",
    durationMs: 1000,
    priority: 50,
    cooldownMs: 0,
    agentSelectable: false,
    tags: [],
  };

  function armTracks() {
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, 0.4));
    return {
      duration: 1,
      rotation: new Map([
        [
          "leftUpperArm" as const,
          new THREE.QuaternionKeyframeTrack(
            "leftUpperArm.quaternion",
            [0, 1],
            [...q.toArray(), ...q.toArray()],
          ),
        ],
      ]),
      expressions: new Map(),
      hipsTranslation: null,
    };
  }

  it("plays authored rotations at full weight while preserving unanimated limbs", async () => {
    const { host, frame, bones } = fixture();
    const stage = await loadVrmStage(host, "/model.vrm");
    stage.driver.playAction(motion, armTracks());
    for (let i = 0; i < 5; i++) frame();
    expect(bones.get("leftUpperArm")!.rotation.z).toBeCloseTo(0.4);
    expect(bones.get("rightUpperArm")!.rotation.z).toBeCloseTo(1.35);
    stage.dispose();
  });

  it("returns to stance after a one-shot finishes", async () => {
    const { host, frame, bones } = fixture();
    const stage = await loadVrmStage(host, "/model.vrm");
    stage.driver.playAction(motion, armTracks());
    for (let i = 0; i < 17; i++) frame();
    expect(bones.get("leftUpperArm")!.rotation.z).toBeCloseTo(-1.35);
    stage.dispose();
  });

  it("does not cancel a pending asset when the previous one-shot finishes", async () => {
    const { host, frame, bones } = fixture();
    const stage = await loadVrmStage(host, "/model.vrm");
    let resolve!: (value: ReturnType<typeof armTracks>) => void;
    mocks.motionLoad.mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    stage.driver.playAction(motion, armTracks());
    stage.driver.playAction({ ...motion, assetUrl: "/next.vrma" });
    await vi.dynamicImportSettled();
    for (let i = 0; i < 17; i++) frame();
    resolve(armTracks());
    await Promise.resolve();
    for (let i = 0; i < 5; i++) frame();
    expect(bones.get("leftUpperArm")!.rotation.z).toBeCloseTo(0.4);
    stage.dispose();
  });

  it("does not play a late asset after its cue is stopped", async () => {
    const { host, frame, bones } = fixture();
    const stage = await loadVrmStage(host, "/model.vrm");
    let resolve!: (value: ReturnType<typeof armTracks>) => void;
    mocks.motionLoad.mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    stage.driver.playAction({ ...motion, assetUrl: "/late.vrma" });
    await vi.dynamicImportSettled();
    stage.driver.stopAction();
    resolve(armTracks());
    await Promise.resolve();
    for (let i = 0; i < 5; i++) frame();
    expect(bones.get("leftUpperArm")!.rotation.z).toBeCloseTo(-1.35);
    stage.dispose();
  });

  it("keeps desktop character height and feet fixed with 20% room above the head", async () => {
    const { host, frame } = fixture();
    const stage = await loadVrmStage(host, "/model.vrm");
    const camera = frame();
    const head = new THREE.Vector3(0, 1.7, 0).project(camera);
    const foot = new THREE.Vector3(0, 0, 0).project(camera);
    expect(head.y).toBeLessThanOrEqual(1);
    expect(foot.y).toBeGreaterThanOrEqual(-1);
    expect(((head.y - foot.y) / 2) * host.clientHeight).toBeCloseTo(TARGET_CHARACTER_HEIGHT, 0);
    expect(((1 - head.y) / 2) * host.clientHeight).toBeCloseTo(
      TARGET_CHARACTER_HEIGHT * VRM_TOP_HEADROOM_RATIO,
      0,
    );
    expect(foot.y).toBeCloseTo(-1);
    const raisedHand = new THREE.Vector3(0, 1.7 * 1.19, 0).project(camera);
    expect(raisedHand.y).toBeLessThan(1);
    Object.defineProperty(host, "clientWidth", { value: 480 });
    mocks.resize?.();
    expect((camera.right - camera.left) / (camera.top - camera.bottom)).toBeCloseTo(
      480 / host.clientHeight,
    );
    Object.defineProperty(host, "clientHeight", { value: 240 });
    mocks.resize?.();
    camera.updateMatrixWorld(true);
    expect(new THREE.Vector3(0, 1.7 * 1.19, 0).project(camera).y).toBeLessThan(1);
    expect(new THREE.Vector3(0, 0, 0).project(camera).y).toBeCloseTo(-1);
    stage.dispose();
  });

  it("applies the stance before declaring the stage ready", async () => {
    const { host, bones } = fixture();
    const stage = await loadVrmStage(host, "/model.vrm");
    expect(Math.abs(bones.get("leftUpperArm")!.rotation.z)).toBeGreaterThan(1);
    expect(mocks.motionLoad).not.toHaveBeenCalled();
    expect(bones.get("leftLowerArm")!.rotation.x).toBeCloseTo(0.12);
    expect(bones.get("leftHand")!.rotation.x).toBeCloseTo(0);
    stage.dispose();
  });

  it("loops the imported idle file and restores static rest when it is removed", async () => {
    const { host, frame, bones } = fixture();
    const stage = await loadVrmStage(host, "/model.vrm");
    stage.driver.setIdleMotion(idleTracks());
    const elbow = bones.get("leftLowerArm")!;
    const initial = elbow.quaternion.clone();
    for (let i = 0; i < 5; i++) frame();
    expect(elbow.quaternion.angleTo(initial)).toBeGreaterThan(0.03);
    for (let i = 0; i < 15; i++) frame();
    expect(elbow.quaternion.angleTo(initial)).toBeLessThan(0.001);
    stage.driver.setIdleMotion(null);
    for (let i = 0; i < 5; i++) frame();
    expect(elbow.rotation.x).toBeCloseTo(0.12);
    const resting = elbow.quaternion.clone();
    for (let i = 0; i < 10; i++) frame();
    expect(elbow.quaternion.angleTo(resting)).toBeLessThan(0.001);
    stage.dispose();
  });

  it("clears prior emotion and face overrides when returning to neutral", async () => {
    const { host, frame, weights } = fixture();
    const stage = await loadVrmStage(host, "/model.vrm");
    stage.driver.applyState("idle", "happy");
    frame();
    stage.driver.setFaceOverride("worried");
    frame();
    expect(weights.get("happy")).toBe(0);
    expect(weights.get("sad")).toBe(0.35);
    stage.driver.setFaceOverride(null);
    stage.driver.applyState("idle", "neutral");
    frame();
    expect(weights.get("sad")).toBe(0);
    expect(weights.get("happy")).toBe(0);
    stage.dispose();
  });

  it("opens the eyes after one blink instead of oscillating for the rest of the cycle", async () => {
    const { host, frame, weights } = fixture();
    const stage = await loadVrmStage(host, "/model.vrm");
    let blinks = 0;
    let closed = false;
    for (let i = 0; i < 400; i++) {
      frame(20);
      const next = (weights.get("blink") ?? 0) > 0;
      if (next && !closed) blinks++;
      closed = next;
    }
    expect(blinks).toBeGreaterThanOrEqual(2);
    expect(blinks).toBeLessThanOrEqual(3);
    stage.dispose();
  });

  it("releases the canvas and renderer when model loading fails", async () => {
    const { host } = fixture();
    mocks.load.mockRejectedValue(new Error("model unavailable"));
    await expect(loadVrmStage(host, "/missing.vrm")).rejects.toThrow("model unavailable");
    expect(mocks.dispose).toHaveBeenCalledOnce();
    expect(mocks.remove).toHaveBeenCalledOnce();
  });

  it("loads and stays still with no bundled or available motion assets", async () => {
    const { host, frame, bones } = fixture();
    mocks.motionLoad.mockRejectedValue(new Error("motion library empty"));
    const stage = await loadVrmStage(host, "/model.vrm");
    const initial = bones.get("head")!.quaternion.clone();
    for (let i = 0; i < 30; i++) frame();
    expect(mocks.motionLoad).not.toHaveBeenCalled();
    expect(bones.get("head")!.quaternion.angleTo(initial)).toBe(0);
    stage.driver.playAction(motion);
    for (let i = 0; i < 5; i++) frame();
    expect(mocks.motionLoad).not.toHaveBeenCalled();
    expect(bones.get("leftUpperArm")!.rotation.z).toBeCloseTo(-1.35);
    stage.dispose();
  });
});
