/**
 * 静态皮肤渲染层（M1-S1，功能清单 3.2/3.4）：单张图片角色的 PIXI 舞台。
 *
 * 与 live2d/core.ts 同构：透明画布 + drag-region + 布局倒置
 * （computeCharacterLayout 推 scale，窗口围绕角色构建）。
 * 动画表达在 staticDriver（正弦漂浮/呼吸/摇摆，ADR-0006 D9）。
 */
import * as PIXI from "pixi.js";
import { MAX_STATIC_UPSCALE, computeCharacterLayout } from "../layout/characterLayout";

/** pixi v6 Loader 包装：图片纹理加载，失败 reject 供调用方降级。 */
function loadTexture(url: string): Promise<PIXI.Texture> {
  return new Promise((resolve, reject) => {
    const loader = new PIXI.Loader();
    loader.add(url);
    loader.load((_ldr, resources) => {
      const resource = resources[url];
      if (resource?.error || !resource?.texture) {
        reject(resource?.error ?? new Error(`图片加载失败：${url}`));
      } else {
        resolve(resource.texture);
      }
    });
  });
}

export interface StaticStageHandle {
  app: PIXI.Application;
  sprite: PIXI.Sprite;
  /** 原图尺寸：布局倒置的事实源（与 StageHandle.modelWidth 同语义）。 */
  modelWidth: number;
  modelHeight: number;
}

/**
 * 在容器内创建透明画布并加载图片角色。锚点底部中心、水平居中、底边对齐；
 * 失败时销毁已建资源并抛出，调用方负责降级。
 */
export async function loadStaticStage(
  container: HTMLElement,
  imageUrl: string,
): Promise<StaticStageHandle> {
  const app = new PIXI.Application({
    backgroundAlpha: 0,
    resizeTo: container,
    resolution: Math.min(window.devicePixelRatio || 1, 2),
    autoDensity: true,
  });
  const canvas = app.view as HTMLCanvasElement;
  canvas.style.display = "block";
  canvas.setAttribute("data-tauri-drag-region", "");
  container.appendChild(canvas);

  try {
    const texture = await loadTexture(imageUrl);
    const sprite = new PIXI.Sprite(texture);
    sprite.anchor.set(0.5, 1);
    // 放大上限封顶：小图不无限拉大发糊（窗口尺寸经 onModelReady 同参闭环）
    sprite.scale.set(
      computeCharacterLayout(texture.width, texture.height, MAX_STATIC_UPSCALE).scale,
    );
    sprite.x = app.screen.width / 2;
    sprite.y = app.screen.height;
    app.stage.addChild(sprite);
    return { app, sprite, modelWidth: texture.width, modelHeight: texture.height };
  } catch (err) {
    app.destroy(true);
    throw err;
  }
}

export function disposeStaticStage(stage: StaticStageHandle): void {
  stage.app.destroy(true, { children: true });
}
