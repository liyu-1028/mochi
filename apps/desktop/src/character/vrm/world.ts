/**
 * VRM 渲染世界（ADR-0011 P0）：Three.js 场景封装——透明桌面常驻窗口用。
 *
 * 与舞蹈原型（components/prototypes/danceStage.ts）的差异：透明背景
 * （窗口层合成）、正交相机（平面桌宠观感 + 布局倒置 pixelsPerMeter 公式
 * 对齐 ADR-0010 D6）、无地面、灯光轻量（省电）。动作预览可启用 OrbitControls。
 */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import {
  BUBBLE_HEADROOM,
  MAX_CHARACTER_WIDTH,
  TARGET_CHARACTER_HEIGHT,
  VRM_TOP_HEADROOM_RATIO,
} from "../../layout/characterLayout";

export interface VrmViewOptions {
  /** preview：居中适配预览容器，并允许拖动相机；默认沿用桌面角色布局。 */
  view?: "desktop" | "preview";
}

export interface VrmWorld {
  readonly scene: THREE.Scene;
  readonly camera: THREE.OrthographicCamera;
  readonly renderer: THREE.WebGLRenderer;
  /** 站姿包围盒（米）：按角色布局取景，resize 时保持比例与脚底锚点。 */
  frame(bounds: THREE.Box3): void;
  updateView(): void;
  resetView(): void;
  dispose(): void;
}

/**
 * 在宿主元素内创建透明 WebGL 画布。
 * 模型与相机均使用米；逻辑像素只用于确定角色在画布中的目标尺寸。
 */
export function createVrmWorld(host: HTMLElement, options: VrmViewOptions = {}): VrmWorld {
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.05, 50);
  camera.position.set(0, 0, 10);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setClearColor(0x000000, 0); // 透明：窗口层负责合成
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const canvas = renderer.domElement;
  canvas.style.display = "block";
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  canvas.style.position = "absolute";
  canvas.style.inset = "0";
  const preview = options.view === "preview";
  canvas.setAttribute("aria-label", preview ? "可拖动旋转的角色预览" : "桌面角色");
  host.appendChild(canvas);

  const controls = preview ? new OrbitControls(camera, canvas) : null;
  if (controls) {
    controls.enableDamping = true;
    controls.enablePan = false;
    controls.minZoom = 0.5;
    controls.maxZoom = 2.5;
    controls.minPolarAngle = Math.PI * 0.15;
    controls.maxPolarAngle = Math.PI * 0.85;
  }

  // 桌宠光照基线：半球环境 + 单侧主光（省电不投影；观感 P1 gate 再调）
  scene.add(new THREE.HemisphereLight(0xffffff, 0xc8c0d0, 2.0));
  const key = new THREE.DirectionalLight(0xfff6ea, 1.9);
  key.position.set(1.5, 3, 4);
  scene.add(key);

  let modelBounds: THREE.Box3 | null = null;
  const resize = () => {
    const w = host.clientWidth;
    const h = host.clientHeight;
    if (w <= 0 || h <= 0) return;
    renderer.setSize(w, h, false);
    if (!modelBounds) return;
    const size = modelBounds.getSize(new THREE.Vector3());
    const center = modelBounds.getCenter(new THREE.Vector3());
    if (preview) {
      // 预览只预留动作活动边距，按整个容器适配，不占用桌面气泡留白。
      const viewHeight = Math.max(size.y, Math.max(size.x, size.z) / (w / h)) * 1.22;
      camera.left = (-viewHeight * (w / h)) / 2;
      camera.right = (viewHeight * (w / h)) / 2;
      camera.bottom = -viewHeight / 2;
      camera.top = viewHeight / 2;
      camera.updateProjectionMatrix();
      return;
    }
    const pixelsPerMeter = Math.min(
      TARGET_CHARACTER_HEIGHT / size.y,
      MAX_CHARACTER_WIDTH / size.x,
      w / size.x,
      // 窗口与相机共用顶部余量，固定脚底与角色大小，空间向上扩展。
      Math.max(1, h - BUBBLE_HEADROOM) / (size.y * (1 + VRM_TOP_HEADROOM_RATIO)),
    );
    camera.left = center.x - w / pixelsPerMeter / 2;
    camera.right = center.x + w / pixelsPerMeter / 2;
    camera.bottom = modelBounds.min.y;
    camera.top = modelBounds.min.y + h / pixelsPerMeter;
    camera.updateProjectionMatrix();
  };
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(host);

  return {
    scene,
    camera,
    renderer,
    frame(bounds) {
      modelBounds = bounds.clone();
      if (controls) {
        const center = bounds.getCenter(new THREE.Vector3());
        controls.target.copy(center);
        camera.position.copy(center).add(new THREE.Vector3(0, 0, 10));
        camera.zoom = 1;
        controls.update();
        controls.saveState();
      }
      resize();
    },
    updateView() {
      controls?.update();
    },
    resetView() {
      if (!controls) return;
      // 清掉拖动惯性后恢复，避免刚松开鼠标就复位时继续偏离正面。
      const damping = controls.enableDamping;
      controls.enableDamping = false;
      controls.update();
      controls.reset();
      controls.enableDamping = damping;
    },
    dispose() {
      resizeObserver.disconnect();
      controls?.dispose();
      renderer.dispose();
      canvas.remove();
    },
  };
}
