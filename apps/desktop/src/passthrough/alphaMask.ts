/**
 * alphaMask —— 角色像素级命中掩码（「点击区域过大」修复的数据层）。
 *
 * 窗口是矩形（含气泡留白/模型包围盒透明边距/dock），但角色只占其中一部分：
 * 掩码把可见角色轮廓（alpha）降采样为小位图，点击/拖拽/鼠标穿透均以
 * 「该点是否命中角色本体」为准，透明区域不再拦截交互。
 *
 * 纯函数（maskFromImageData/dilate/maskOpaqueAt）可直测；DOM 读取
 * （buildMaskFromCanvas/Image）是薄封装，jsdom 不覆盖。
 */

/** alpha 判定阈值（0..255）：≥ 此值视为角色本体（≈6% 不透明度）。 */
export const ALPHA_THRESHOLD = 16;

/** 掩码降采样上限（px）：掩码精度只需容忍几像素误差，越小轮询越省。 */
export const MASK_MAX_DIM = 200;

/** 掩码默认膨胀半径（掩码 px）：静态皮肤漂浮/Live2D 动作轮廓漂移容差。 */
export const MASK_DILATE_RADIUS = 2;

export interface AlphaMask {
  width: number;
  height: number;
  /** 行主序 alpha（0..255），已膨胀。 */
  alpha: Uint8Array;
}

/** 从 ImageData 抽取 alpha 通道并膨胀（盒状 max 滤波，水平/垂直两趟实现）。 */
export function maskFromImageData(
  data: { width: number; height: number; data: Uint8ClampedArray | Uint8Array },
  dilateRadius: number = MASK_DILATE_RADIUS,
): AlphaMask {
  const { width, height } = data;
  const src = new Uint8Array(width * height);
  for (let i = 0; i < src.length; i += 1) src[i] = data.data[i * 4 + 3];
  return { width, height, alpha: dilate(src, width, height, dilateRadius) };
}

/** 盒状膨胀（max 滤波）：半径 0 原样返回拷贝。两趟分离实现，O(n·r)。 */
export function dilate(src: Uint8Array, width: number, height: number, radius: number): Uint8Array {
  if (radius <= 0) return src.slice();
  let cur = src;
  // 水平趟
  let next = new Uint8Array(src.length);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      let m = 0;
      const from = Math.max(0, x - radius);
      const to = Math.min(width - 1, x + radius);
      for (let i = from; i <= to; i += 1) {
        const v = cur[y * width + i];
        if (v > m) m = v;
        if (m === 255) break;
      }
      next[y * width + x] = m;
    }
  }
  cur = next;
  // 垂直趟
  next = new Uint8Array(src.length);
  for (let y = 0; y < height; y += 1) {
    const from = Math.max(0, y - radius);
    const to = Math.min(height - 1, y + radius);
    for (let x = 0; x < width; x += 1) {
      let m = 0;
      for (let i = from; i <= to; i += 1) {
        const v = cur[i * width + x];
        if (v > m) m = v;
        if (m === 255) break;
      }
      next[y * width + x] = m;
    }
  }
  return next;
}

/**
 * 视口坐标 → 掩码采样：x/y 为舞台矩形内的 CSS px（左上原点），
 * viewW/viewH 为舞台尺寸（掩码与舞台等比映射）。越界视为未命中。
 */
export function maskOpaqueAt(
  mask: AlphaMask,
  x: number,
  y: number,
  viewW: number,
  viewH: number,
  threshold: number = ALPHA_THRESHOLD,
): boolean {
  if (viewW <= 0 || viewH <= 0) return false;
  const mx = Math.floor((x / viewW) * mask.width);
  const my = Math.floor((y / viewH) * mask.height);
  if (mx < 0 || my < 0 || mx >= mask.width || my >= mask.height) return false;
  return mask.alpha[my * mask.width + mx] >= threshold;
}

/** 画布 → 掩码：降采样到 MASK_MAX_DIM 再抽 alpha（等比映射，见 maskOpaqueAt）。 */
export function buildMaskFromCanvas(
  canvas: HTMLCanvasElement | HTMLImageElement | ImageBitmap,
  dilateRadius: number = MASK_DILATE_RADIUS,
): AlphaMask {
  const w = canvas.width;
  const h = canvas.height;
  if (w <= 0 || h <= 0) throw new Error("掩码源尺寸为 0");
  const scale = Math.min(1, MASK_MAX_DIM / Math.max(w, h));
  const tw = Math.max(1, Math.round(w * scale));
  const th = Math.max(1, Math.round(h * scale));
  const off = document.createElement("canvas");
  off.width = tw;
  off.height = th;
  const ctx = off.getContext("2d", { willReadFrequently: true });
  if (!ctx) throw new Error("2D 上下文不可用（掩码构建失败）");
  ctx.drawImage(canvas, 0, 0, w, h, 0, 0, tw, th);
  return maskFromImageData(ctx.getImageData(0, 0, tw, th), dilateRadius);
}

/** 图片 URL → 掩码（静态皮肤路径：源图即轮廓）。
 *  crossOrigin 必需：用户皮肤资源由 sidecar 跨源分发（127.0.0.1:8199），
 *  缺省加载会污染 canvas → getImageData 抛 SecurityError → 掩码构建失败；
 *  sidecar CORS 白名单已放行前端源（security.py），带凭证拉取不回落。 */
export async function buildMaskFromImage(
  url: string,
  dilateRadius: number = MASK_DILATE_RADIUS,
): Promise<AlphaMask> {
  const img = new Image();
  img.crossOrigin = "anonymous";
  img.src = url;
  await img.decode();
  return buildMaskFromCanvas(img, dilateRadius);
}
