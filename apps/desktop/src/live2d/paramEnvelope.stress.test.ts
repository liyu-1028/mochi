import { describe, expect, it } from "vitest";
import { compileParamEnvelope } from "./paramEnvelope";

describe("compileParamEnvelope (压力与防御性边界测试)", () => {
  it("极限时间戳：1000 个密集关键帧平滑插值", () => {
    const points: [number, number][] = [];
    for (let i = 0; i <= 1000; i += 1) {
      points.push([i, Math.sin((i / 1000) * Math.PI)]);
    }
    const env = compileParamEnvelope({
      durationMs: 1000,
      keyframes: [{ param: "ParamAngleX", points }],
    });
    expect(env).not.toBeNull();
    expect(env!.params(500).ParamAngleX).toBeCloseTo(1.0, 4);
    expect(env!.params(0).ParamAngleX).toBeCloseTo(0.0, 4);
    expect(env!.params(1000).ParamAngleX).toBeCloseTo(0.0, 4);
  });

  it("防御性检查：包含非有限数字（Infinity / -Infinity / NaN）一律安全返回 null", () => {
    // 时间戳包含 Infinity
    expect(
      compileParamEnvelope({
        durationMs: 500,
        keyframes: [
          {
            param: "P",
            points: [
              [0, 0],
              [Number.POSITIVE_INFINITY, 1],
            ],
          },
        ],
      }),
    ).toBeNull();

    // 关键帧值包含 -Infinity
    expect(
      compileParamEnvelope({
        durationMs: 500,
        keyframes: [
          {
            param: "P",
            points: [
              [0, 0],
              [500, Number.NEGATIVE_INFINITY],
            ],
          },
        ],
      }),
    ).toBeNull();

    // 关键帧值包含 NaN
    expect(
      compileParamEnvelope({
        durationMs: 500,
        keyframes: [
          {
            param: "P",
            points: [
              [0, 0],
              [500, Number.NaN],
            ],
          },
        ],
      }),
    ).toBeNull();
  });

  it("防御性检查：时间戳倒流或相等一律安全返回 null", () => {
    expect(
      compileParamEnvelope({
        durationMs: 500,
        keyframes: [
          {
            param: "P",
            points: [
              [0, 0],
              [200, 1],
              [150, 0.5], // 倒流
              [500, 0],
            ],
          },
        ],
      }),
    ).toBeNull();

    expect(
      compileParamEnvelope({
        durationMs: 500,
        keyframes: [
          {
            param: "P",
            points: [
              [0, 0],
              [200, 1],
              [200, 0.5], // 相等重复
              [500, 0],
            ],
          },
        ],
      }),
    ).toBeNull();
  });

  it("防御性检查：首点时间非 0 返回 null", () => {
    expect(
      compileParamEnvelope({
        durationMs: 500,
        keyframes: [
          {
            param: "P",
            points: [
              [1, 0],
              [500, 1],
            ],
          },
        ],
      }),
    ).toBeNull();
  });

  it("端点平滑度：smoothstep 在边界处的导数为 0（平滑缓入缓出）", () => {
    const env = compileParamEnvelope({
      durationMs: 1000,
      easing: "smoothstep",
      keyframes: [
        {
          param: "P",
          points: [
            [0, 0],
            [1000, 100],
          ],
        },
      ],
    });
    expect(env).not.toBeNull();
    // 在 1% 处，smoothstep(0.01) = 3*(0.01)^2 - 2*(0.01)^3 = 0.000298 << 0.01 (线性 1.0)
    expect(env!.params(10).P).toBeCloseTo(0.0298, 2);
    // 在 99% 处，缓出同样极其平缓
    expect(env!.params(990).P).toBeCloseTo(99.9702, 2);
  });
});
