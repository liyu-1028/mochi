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
  // 画布本身也是窗口拖拽区（data-tauri-drag-region，功能清单 1.3）
  canvas.setAttribute("data-tauri-drag-region", "");
  container.appendChild(canvas);

  try {
    // autoInteract 关闭：视线跟随由 gaze 驱动显式 focus，避免点击劫持；
    // motionPreload=ALL：状态切换时动作零加载延迟（2.2 切换 ≤300ms 的前提）
    const { MotionPreloadStrategy } = await importLive2D();
    const model = await ModelCtor.from(modelUrl, {
      autoInteract: false,
      motionPreload: MotionPreloadStrategy.ALL,
    });
    app.stage.addChild(model);
    placeModel(model, app, computeCharacterLayout(model.width, model.height).scale);
    return { app, model, modelWidth: model.width, modelHeight: model.height };
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
  model.y = height - (model.height * scale) / 2;
}

export function disposeStage(stage: StageHandle): void {
  stage.app.destroy(true, { children: true });
}
