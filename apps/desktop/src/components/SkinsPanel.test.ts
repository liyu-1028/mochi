/**
 * SkinsPanel 导入尺寸归一化纯函数测试（node 环境直测，仓库惯例）。
 */
import { describe, expect, it } from "vitest";
import { IMPORT_MAX_EDGE, decidePngNormalization } from "./SkinsPanel";

describe("decidePngNormalization", () => {
  it("常规尺寸：不压缩、不提示", () => {
    expect(decidePngNormalization(1920, 1920)).toEqual({ downscaleTo: null, small: false });
    expect(decidePngNormalization(736, 1308)).toEqual({ downscaleTo: null, small: false });
  });

  it("长边超限：压缩到 IMPORT_MAX_EDGE", () => {
    expect(decidePngNormalization(4096, 3000).downscaleTo).toBe(IMPORT_MAX_EDGE);
    expect(decidePngNormalization(3000, 4096).downscaleTo).toBe(IMPORT_MAX_EDGE);
  });

  it("边界：长边恰 2048 不压缩", () => {
    expect(decidePngNormalization(2048, 1000).downscaleTo).toBeNull();
  });

  it("小图软提示：max 边 <256（snj 形状走导入也会提示；内置不走导入）", () => {
    expect(decidePngNormalization(148, 209).small).toBe(true);
    expect(decidePngNormalization(209, 148).small).toBe(true);
    expect(decidePngNormalization(256, 256).small).toBe(false);
  });

  it("又小又超？不可能同现：small 与 downscale 互斥语义", () => {
    const d = decidePngNormalization(100, 100);
    expect(d.small).toBe(true);
    expect(d.downscaleTo).toBeNull();
  });
});
