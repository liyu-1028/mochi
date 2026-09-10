/**
 * Live2D 运行时封装（M0-S3，ADR-0003）。
 *
 * Cubism Core 由 index.html 的 script 标签注入 `window.Live2D`（专有代码，
 * 脚本下载不入库）；渲染库在 Core 就绪后**动态导入**。
 * Core 或模型缺失时抛错，由 CharacterStage 捕获并降级回 emoji 占位。
 */
import * as PIXI from "pixi.js";
import type { Live2DModel } from "pixi-live2d-display/cubism4";
import { computeCharacterLayout } from "../layout/characterLayout";

export type { Live2DModel };

/** 内置 Live2D 默认模型 URL（用户可自行导入 Live2D 皮肤包替换）。 */
export const DEFAULT_MODEL_URL = "/skins/pikachu/avatar.png";

export function isCubismCoreReady(): boolean {
  return typeof window !== "undefined" && (window as { Live2D?: unknown }).Live2D !== undefined;
}

let live2dModule: Promise<typeof import("pixi-live2d-display/cubism4")> | null = null;

/** 动态导入渲染库（模块求值依赖 Core 全局，必须先过 isCubismCoreReady）。 */
export function importLive2D(): Promise<typeof import("pixi-live2d-display/cubism4")> {
  live2dModule ??= import("pixi-live2d-display/cubism4");
  return live2dModule;
}

export interface StageHandle {
  app: PIXI.Application;
  model: Live2DModel;
  /** 模型原始尺寸：布局倒置的事实源（characterLayout 据此推导 scale/窗口）。 */
  modelWidth: number;
  modelHeight: number;
}

/**
 * 在容器内创建透明 PIXI 画布并加载模型。
 * 失败时销毁已建资源并抛出，调用方负责降级。
 */
export async function loadCharacterStage(
  container: HTMLElement,
  modelUrl: string,
): Promise<StageHandle> {
  if (!isCubismCoreReady()) {
    throw new Error("Live2D Cubism Core 未加载（window.Live2D 缺失）");
  }
  const { Live2DModel: ModelCtor } = await importLive2D();
  const app = new PIXI.Application({
    backgroundAlpha: 0,
    resizeTo: container,
    // 4K 屏不超采样（功能清单 2.1 性能基线，Phase 7 细化）
    resolution: Math.min(window.devicePixelRatio || 1, 2),
    autoDensity: true,
  });
  const canvas = app.view as HTMLCanvasElement;
  canvas.style.display = "block";
  // 拖拽不再用铺满画布的 data-tauri-drag-region（点击区域过大缺陷源）：
  // 改由 CharacterStage 命中角色本体后自绘 startDragging（见 1.3）
  container.appendChild(canvas);

  try {
    // autoInteract 关闭：视线跟随由 gaze 驱动显式 focus，避免点击劫持；
    // autoUpdate 关闭：Vite ESM 下无全局 window.PIXI，库内自动驱动会报
    // “No Ticker registered” 且内部状态永不推进；改为绑定 app.ticker
    // 手动 update（省电降档/窗口隐藏时随渲染一起停）；
    // motionPreload=ALL：状态切换时动作零加载延迟（2.2 切换 ≤300ms 的前提）
    const { MotionPreloadStrategy } = await importLive2D();
    const model = await ModelCtor.from(modelUrl, {
      autoInteract: false,
      autoUpdate: false,
      motionPreload: MotionPreloadStrategy.ALL,
    });
    app.stage.addChild(model);
    // 画布尺寸以 internalModel.originalWidth/Height 为准（模型逻辑画布，
    // 不受 Container bounds/scale 语义影响）；model.width/height 在
    // scale 置入后会变成“已缩放的显示尺寸”，历史上传出去导致布局二次推导
    const canvasW = model.internalModel.originalWidth;
    const canvasH = model.internalModel.originalHeight;
    const scale = computeCharacterLayout(canvasW, canvasH).scale;
    placeModel(model, app, scale);
    // 每帧重取基准位置（同 staticDriver tick 语义）：布局倒置下窗口在模型
    // 就绪后才异步 setSize（onModelReady → applyCharacterLayout），画布
    // resizeTo 跟随，但模型若只在加载时定位一次会停留在旧画布坐标系里
    // ——冷启动/换肤尺寸变化时被裁切（时显时不显的根因）
    const reposition = () => {
      // autoUpdate=false：模型内部状态（动作/呼吸/眼球平滑）随本 ticker 推进
      model.update(app.ticker.deltaMS);
      if (app.screen.width <= 0 || app.screen.height <= 0) return;
      model.x = app.screen.width / 2;
      model.y = app.screen.height - (canvasH * model.scale.y) / 2;
    };
    app.ticker.add(reposition);
    console.info(
      `[mochi] live2d-stage canvas=${canvasW}x${canvasH} scale=${scale.toFixed(3)} screen=${app.screen.width}x${app.screen.height}`,
    );
    return { app, model, modelWidth: canvasW, modelHeight: canvasH };
  } catch (err) {
    app.destroy(true);
    throw err;
  }
}

/** 以外部推导的 scale 放置模型：水平居中、底边对齐。
 * scale 由 characterLayout 按角色目标像素尺寸纯函数推导（不依赖 canvas）；
 * 窗口/canvas 围绕模型包围盒构建，头顶 BUBBLE_HEADROOM 留给气泡叠层区
 * （气泡在画布图层之上、按屏幕位置选边侧向贴头，styles.css .bubbles）。 */
function placeModel(model: Live2DModel, app: PIXI.Application, scale: number): void {
  const { width, height } = app.screen;
  model.scale.set(scale);
  model.anchor.set(0.5, 0.5);
  model.x = width / 2;
  // anchor(0.5,0.5) 下 model.y 为模型中心：底边对齐 = 屏高 - 显示高(画布高×scale)/2
  model.y = height - (model.internalModel.originalHeight * scale) / 2;
}

export function disposeStage(stage: StageHandle): void {
  stage.app.destroy(true, { children: true });
}
