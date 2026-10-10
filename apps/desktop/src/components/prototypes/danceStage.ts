/** PROTOTYPE — 只验证现成 VRM + 全身舞蹈，不接入生产角色导演。 */
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { VRMLoaderPlugin, VRMUtils, type VRM } from "@pixiv/three-vrm";
import { loadDance } from "./retargetDance";

export interface DanceSnapshot {
  time: number;
  duration: number;
  fps: number;
  tracks: number;
  playing: boolean;
}

export function createDanceStage(
  host: HTMLDivElement,
  onSnapshot: (snapshot: DanceSnapshot) => void,
  onStatus: (status: string) => void,
  onError: (error: string) => void,
) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#eeeaf3");
  const camera = new THREE.PerspectiveCamera(33, 1, 0.05, 50);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.setAttribute("aria-label", "可拖动旋转的三维舞蹈舞台");
  host.appendChild(renderer.domElement);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.minDistance = 1.5;
  controls.maxDistance = 8;
  controls.maxPolarAngle = Math.PI * 0.49;
  controls.target.set(0, 0.95, 0);
  camera.position.set(0.3, 1.35, 4.5);
  controls.update();

  scene.add(new THREE.HemisphereLight(0xffffff, 0xb3a7bf, 2.1));
  const key = new THREE.DirectionalLight(0xfff4e8, 2.4);
  key.position.set(2, 4, 3);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  Object.assign(key.shadow.camera, {
    left: -2.5,
    right: 2.5,
    top: 2.5,
    bottom: -2.5,
    near: 0.1,
    far: 12,
  });
  key.shadow.normalBias = 0.025;
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xc6cdff, 1.3);
  fill.position.set(-3, 2, -2);
  scene.add(fill);

  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(200, 200),
    new THREE.MeshStandardMaterial({
      color: "#eeeaf3",
      roughness: 1,
    }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -0.008;
  floor.receiveShadow = true;
  scene.add(floor);
  const grid = new THREE.GridHelper(10, 40, 0xb2a4c2, 0xd8d0e2);
  grid.position.y = -0.004;
  scene.add(grid);

  let disposed = false;
  let vrm: VRM | null = null;
  let mixer: THREE.AnimationMixer | null = null;
  let clip: THREE.AnimationClip | null = null;
  let action: THREE.AnimationAction | null = null;
  let playing = true;
  let speed = 1;
  let loop = true;
  let lastFrame = performance.now();
  let lastReport = lastFrame;
  let frameCount = 0;
  let fps = 0;

  function snapshot() {
    onSnapshot({
      time: action?.time ?? 0,
      duration: clip?.duration ?? 0,
      tracks: clip?.tracks.length ?? 0,
      playing,
      fps,
    });
  }
  function resize() {
    const width = host.clientWidth;
    const height = host.clientHeight;
    if (!width || !height) return;
    renderer.setSize(width, height);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }
  const observer = new ResizeObserver(resize);
  observer.observe(host);
  resize();
  const resetClock = () => {
    lastFrame = performance.now();
    lastReport = lastFrame;
    frameCount = 0;
  };
  document.addEventListener("visibilitychange", resetClock);

  async function load() {
    try {
      onStatus("正在加载全身角色…");
      const loader = new GLTFLoader();
      loader.register((parser) => new VRMLoaderPlugin(parser));
      const gltf = await loader.loadAsync("/prototype-assets/sample.vrm");
      const model = gltf.userData.vrm as VRM | undefined;
      if (!model) throw new Error("资源不是可识别的 VRM 模型");
      if (disposed) {
        VRMUtils.deepDispose(model.scene);
        return;
      }
      vrm = model;
      VRMUtils.removeUnnecessaryVertices(model.scene);
      model.scene.traverse((object) => {
        object.frustumCulled = false;
        if (object instanceof THREE.Mesh) {
          object.castShadow = true;
          object.receiveShadow = false;
        }
      });
      onStatus("正在映射 Samba 全身舞蹈…");
      const dance = await loadDance(model);
      if (disposed) return;
      clip = dance;
      mixer = new THREE.AnimationMixer(model.scene);
      action = mixer.clipAction(dance);
      action.setLoop(THREE.LoopRepeat, Infinity).play();
      action.clampWhenFinished = true;
      mixer.addEventListener("finished", () => {
        playing = false;
        snapshot();
      });
      mixer.update(0);
      model.update(0);
      // 仅校准初始落地高度，不每帧拉回地面，保留跳起和重心变化。
      model.scene.updateMatrixWorld(true);
      const bounds = new THREE.Box3().setFromObject(model.scene);
      model.scene.position.y -= bounds.min.y;
      model.expressionManager?.setValue("happy", 0.22);
      scene.add(model.scene);
      onStatus("Samba Dancing · 全身动作");
      snapshot();
    } catch (error) {
      if (!disposed) onError(error instanceof Error ? error.message : String(error));
    }
  }
  void load();

  renderer.setAnimationLoop((now: number) => {
    const delta = Math.min(Math.max((now - lastFrame) / 1000, 0), 0.05);
    lastFrame = now;
    if (document.hidden) return;
    if (mixer && vrm && action) {
      if (playing) {
        mixer.update(delta * speed);
        const phase = action.time % 4.2;
        vrm.expressionManager?.setValue(
          "blink",
          phase < 0.16 ? Math.sin((phase / 0.16) * Math.PI) : 0,
        );
        vrm.update(delta * speed);
      }
    }
    controls.update();
    renderer.render(scene, camera);
    frameCount++;
    if (now - lastReport >= 250) {
      fps = Math.round((frameCount * 1000) / (now - lastReport));
      lastReport = now;
      frameCount = 0;
      snapshot();
    }
  });

  return {
    toggle() {
      if (!action) return;
      if (!playing && action.time >= action.getClip().duration) action.reset().play();
      playing = !playing;
      snapshot();
    },
    restart() {
      action?.reset().play();
      vrm?.springBoneManager?.reset();
      playing = true;
      snapshot();
    },
    seek(time: number) {
      if (!action || !mixer || !vrm) return;
      playing = false;
      action.paused = false;
      action.enabled = true;
      action.time = THREE.MathUtils.clamp(time, 0, action.getClip().duration - 0.0001);
      mixer.update(0);
      vrm.update(0);
      vrm.springBoneManager?.reset();
      snapshot();
    },
    setSpeed(value: number) {
      speed = value;
    },
    setLoop(value: boolean) {
      loop = value;
      action?.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, loop ? Infinity : 1);
    },
    setGrid(value: boolean) {
      grid.visible = value;
    },
    view(angle: number) {
      controls.target.set(0, 0.95, 0);
      camera.position.set(Math.sin(angle) * 4.5, 1.35, Math.cos(angle) * 4.5);
      controls.update();
    },
    dispose() {
      disposed = true;
      renderer.setAnimationLoop(null);
      observer.disconnect();
      document.removeEventListener("visibilitychange", resetClock);
      mixer?.stopAllAction();
      if (vrm) {
        mixer?.uncacheRoot(vrm.scene);
        VRMUtils.deepDispose(vrm.scene);
      }
      floor.geometry.dispose();
      floor.material.dispose();
      grid.geometry.dispose();
      const materials = Array.isArray(grid.material) ? grid.material : [grid.material];
      materials.forEach((material) => material.dispose());
      key.shadow.dispose();
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}

export type DanceStage = ReturnType<typeof createDanceStage>;
