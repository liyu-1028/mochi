/** WAV 编码纯函数测试：RIFF 头字节 / 长度字段 / 截幅。 */
import { describe, expect, it } from "vitest";
import { encodeWavPcm16 } from "./wav";

describe("encodeWavPcm16", () => {
  it("RIFF/fmt/data 头与长度字段正确", () => {
    const samples = new Float32Array([0, 0.5, -0.5]);
    const buf = encodeWavPcm16(samples);
    const view = new DataView(buf);
    const tag = (offset: number, len: number) =>
      String.fromCharCode(...new Uint8Array(buf, offset, len));
    expect(tag(0, 4)).toBe("RIFF");
    expect(view.getUint32(4, true)).toBe(36 + samples.length * 2);
    expect(tag(8, 4)).toBe("WAVE");
    expect(tag(12, 4)).toBe("fmt ");
    expect(view.getUint16(20, true)).toBe(1); // PCM
    expect(view.getUint16(22, true)).toBe(1); // 单声道
    expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getUint16(34, true)).toBe(16); // 位深
    expect(tag(36, 4)).toBe("data");
    expect(view.getUint32(40, true)).toBe(samples.length * 2);
  });

  it("采样映射与截幅", () => {
    const buf = encodeWavPcm16(new Float32Array([1, -1, 2, -2]));
    const view = new DataView(buf);
    expect(view.getInt16(44, true)).toBe(0x7fff); // +1 → 上限
    expect(view.getInt16(46, true)).toBe(-0x8000); // -1 → 下限
    expect(view.getInt16(48, true)).toBe(0x7fff); // 超界截幅
    expect(view.getInt16(50, true)).toBe(-0x8000);
  });
});
