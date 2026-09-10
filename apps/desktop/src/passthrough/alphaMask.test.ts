/**
 * alphaMask 纯函数测试：alpha 抽取 + 膨胀 + 视图坐标映射。
 * DOM 封装（buildMaskFromCanvas/Image）依赖 2D 上下文，jsdom 不覆盖。
 */
import { describe, expect, it } from "vitest";
import { ALPHA_THRESHOLD, dilate, maskFromImageData, maskOpaqueAt } from "./alphaMask";

/** 合成 ImageData（只关心 alpha，RGB 全 0）。 */
function imageData(width: number, height: number, alphaAt: (x: number, y: number) => number) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) data[(y * width + x) * 4 + 3] = alphaAt(x, y);
  }
  return { width, height, data };
}

describe("maskFromImageData", () => {
  it("抽取 alpha 通道（阈值内视为角色）", () => {
    const mask = maskFromImageData(
      imageData(2, 1, (x) => (x === 0 ? 255 : 0)),
      0,
    );
    expect(mask.alpha).toEqual(new Uint8Array([255, 0]));
  });

  it("膨胀向外扩 r 像素（边缘更易命中）", () => {
    // 3x3 中心一个不透明点，r=1 后 3x3 全命中
    const mask = maskFromImageData(
      imageData(3, 3, (x, y) => (x === 1 && y === 1 ? 255 : 0)),
      1,
    );
    expect(mask.alpha.every((v) => v === 255)).toBe(true);
  });
});

describe("dilate", () => {
  it("半径 0 返回原样拷贝", () => {
    const src = new Uint8Array([0, 128, 255]);
    expect(dilate(src, 3, 1, 0)).toEqual(src);
  });

  it("盒状 max：行内取邻域最大", () => {
    const src = new Uint8Array([0, 0, 255, 0, 0]);
    const out = dilate(src, 5, 1, 1);
    expect(Array.from(out)).toEqual([0, 255, 255, 255, 0]);
  });
});

describe("maskOpaqueAt", () => {
  const mask = maskFromImageData(
    imageData(4, 4, (x) => (x < 2 ? 255 : 0)),
    0,
  );

  it("视图坐标等比映射到掩码（左半命中、右半不命中）", () => {
    expect(maskOpaqueAt(mask, 10, 20, 40, 40)).toBe(true); // mx=1
    expect(maskOpaqueAt(mask, 30, 20, 40, 40)).toBe(false); // mx=3
  });

  it("低于阈值的半透明视为透明", () => {
    const faint = maskFromImageData(
      imageData(1, 1, () => ALPHA_THRESHOLD - 1),
      0,
    );
    expect(maskOpaqueAt(faint, 0, 0, 10, 10)).toBe(false);
  });

  it("越界与非正视图尺寸不命中", () => {
    expect(maskOpaqueAt(mask, -1, 0, 40, 40)).toBe(false);
    expect(maskOpaqueAt(mask, 0, 99, 40, 40)).toBe(false);
    expect(maskOpaqueAt(mask, 1, 1, 0, 0)).toBe(false);
  });
});
