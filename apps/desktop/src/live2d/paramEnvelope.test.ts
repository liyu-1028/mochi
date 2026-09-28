import { describe, expect, it } from "vitest";

import { compileParamEnvelope } from "./paramEnvelope";

const winkDecl = {
  durationMs: 700,
  keyframes: [
    {
      param: "ParamEyeLOpen",
      points: [
        [0, 1],
        [350, 0],
        [700, 1],
      ] as const,
    },
    {
      param: "ParamMouthForm",
      points: [
        [0, 0],
        [200, 0.6],
        [700, 0],
      ] as const,
    },
  ],
};

describe("compileParamEnvelope", () => {
  it("线性插值：中点取段内比例值", () => {
    const env = compileParamEnvelope(winkDecl);
    expect(env).not.toBeNull();
    expect(env!.durationMs).toBe(700);
    // 0→200ms：t=175 在该段 f=0.875
    expect(env!.params(175)).toEqual({ ParamEyeLOpen: 0.5, ParamMouthForm: 0.525 });
    // 200→700ms：t=525 在该段 f=0.65，0.6 → 0 回落
    expect(env!.params(525).ParamEyeLOpen).toBe(0.5);
    expect(env!.params(525).ParamMouthForm).toBeCloseTo(0.21, 10);
  });

  it("端点钳制：越界时间保持首末点值", () => {
    const env = compileParamEnvelope(winkDecl);
    expect(env!.params(-50)).toEqual({ ParamEyeLOpen: 1, ParamMouthForm: 0 });
    expect(env!.params(9999)).toEqual({ ParamEyeLOpen: 1, ParamMouthForm: 0 });
    expect(env!.params(0)).toEqual({ ParamEyeLOpen: 1, ParamMouthForm: 0 });
    expect(env!.params(700)).toEqual({ ParamEyeLOpen: 1, ParamMouthForm: 0 });
  });

  it("smoothstep：段中点仍是对称中值，四分之一处偏向端点", () => {
    const env = compileParamEnvelope({
      durationMs: 700,
      easing: "smoothstep",
      keyframes: [
        {
          param: "ParamAngleX",
          points: [
            [0, 0],
            [700, 10],
          ],
        },
      ],
    });
    // f=0.5 → smoothstep(0.5)=0.5
    expect(env!.params(350).ParamAngleX).toBeCloseTo(5, 10);
    // f=0.25 → smoothstep(0.25)=0.15625（比线性 0.25 更贴近起点）
    expect(env!.params(175).ParamAngleX).toBeCloseTo(1.5625, 10);
  });

  it("线性为缺省 easing", () => {
    const env = compileParamEnvelope({
      durationMs: 100,
      keyframes: [
        {
          param: "P",
          points: [
            [0, 0],
            [100, 10],
          ],
        },
      ],
    });
    expect(env!.params(50).P).toBe(5);
  });

  it("畸形声明返回 null（防御性，不抛异常）", () => {
    expect(compileParamEnvelope(null)).toBeNull();
    expect(compileParamEnvelope(undefined)).toBeNull();
    // duration 非法
    expect(compileParamEnvelope({ durationMs: 0, keyframes: [] })).toBeNull();
    // keyframes 为空
    expect(compileParamEnvelope({ durationMs: 700, keyframes: [] })).toBeNull();
    // 点数不足
    expect(
      compileParamEnvelope({
        durationMs: 700,
        keyframes: [{ param: "P", points: [[0, 1]] }],
      }),
    ).toBeNull();
    // 时间戳非严格递增
    expect(
      compileParamEnvelope({
        durationMs: 700,
        keyframes: [
          {
            param: "P",
            points: [
              [0, 1],
              [0, 1],
            ],
          },
        ],
      }),
    ).toBeNull();
    // 首点不为 0
    expect(
      compileParamEnvelope({
        durationMs: 700,
        keyframes: [
          {
            param: "P",
            points: [
              [100, 1],
              [700, 1],
            ],
          },
        ],
      }),
    ).toBeNull();
    // param 为空
    expect(
      compileParamEnvelope({
        durationMs: 700,
        keyframes: [
          {
            param: "",
            points: [
              [0, 1],
              [700, 1],
            ],
          },
        ],
      }),
    ).toBeNull();
    // 值非有限数
    expect(
      compileParamEnvelope({
        durationMs: 700,
        keyframes: [
          {
            param: "P",
            points: [
              [0, Number.NaN],
              [700, 1],
            ],
          },
        ],
      }),
    ).toBeNull();
  });
});
