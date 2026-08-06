/**
 * PersonaSection 纯函数测试：编辑态 ⇄ 服务端形状互转、互斥选择、payload 组装。
 * （node 环境直测导出函数，仓库惯例；渲染交互走 GUI 人工验证。）
 */
import { describe, expect, it } from "vitest";
import type { PersonaSettings } from "../api/configClient";
import {
  buildPersonaPayload,
  draftFromSettings,
  emptyDrafts,
  personaDirty,
  presetLabel,
  selectCustom,
  selectPreset,
  type DimensionDraft,
} from "./PersonaSection";

const EMPTY: PersonaSettings = {
  soulPreset: "",
  soulCustom: "",
  personalityPreset: "",
  personalityCustom: "",
  stylePreset: "",
  styleCustom: "",
};

const draft = (over: Partial<DimensionDraft> = {}): DimensionDraft => ({
  presetId: "",
  customText: "",
  customSelected: false,
  ...over,
});

describe("draftFromSettings", () => {
  it("custom 非空 → 自定义模式", () => {
    const d = draftFromSettings("warm_sun", " 自定义文本 ");
    expect(d.customSelected).toBe(true);
    expect(d.customText).toBe(" 自定义文本 ");
    expect(d.presetId).toBe("warm_sun");
  });

  it("custom 为空白 → 预设模式", () => {
    const d = draftFromSettings("warm_sun", "   ");
    expect(d.customSelected).toBe(false);
    expect(d.customText).toBe("");
    expect(d.presetId).toBe("warm_sun");
  });
});

describe("互斥选择", () => {
  it("selectPreset 清除自定义", () => {
    const d = selectPreset(draft({ customSelected: true, customText: "旧文本" }), "warm_sun");
    expect(d).toEqual({ presetId: "warm_sun", customText: "", customSelected: false });
  });

  it("selectCustom 清除预设并保留已输入文本", () => {
    const d = selectCustom(draft({ presetId: "warm_sun", customText: "草稿" }));
    expect(d.presetId).toBe("");
    expect(d.customSelected).toBe(true);
    expect(d.customText).toBe("草稿");
  });
});

describe("buildPersonaPayload", () => {
  it("三维预设 + 一维自定义组合成全量六字段", () => {
    const payload = buildPersonaPayload({
      soul: draft({ presetId: "warm_sun" }),
      personality: draft({ presetId: "sharp_thinker" }),
      style: draft({ customSelected: true, customText: " 说话像海盗 " }),
    });
    expect(payload).toEqual({
      soulPreset: "warm_sun",
      soulCustom: "",
      personalityPreset: "sharp_thinker",
      personalityCustom: "",
      stylePreset: "", // 自定义模式下 preset 清空
      styleCustom: "说话像海盗", // custom 去除首尾空白
    });
  });

  it("全空草稿 → 全空 payload（恢复默认）", () => {
    expect(buildPersonaPayload(emptyDrafts())).toEqual(EMPTY);
  });
});

describe("personaDirty", () => {
  const initial: PersonaSettings = { ...EMPTY, soulPreset: "warm_sun" };

  it("编辑态与初始一致 → 不脏", () => {
    const drafts = {
      soul: draft({ presetId: "warm_sun" }),
      personality: draft(),
      style: draft(),
    };
    expect(personaDirty(initial, drafts)).toBe(false);
  });

  it("改变任一维度 → 脏", () => {
    const drafts = {
      soul: draft({ presetId: "quiet_guardian" }),
      personality: draft(),
      style: draft(),
    };
    expect(personaDirty(initial, drafts)).toBe(true);
  });

  it("自定义模式带空文本等价于未配置 → 不脏", () => {
    const drafts = {
      soul: draft({ presetId: "warm_sun" }),
      personality: draft(),
      style: draft({ customSelected: true, customText: "   " }),
    };
    expect(personaDirty(initial, drafts)).toBe(false);
  });
});

describe("presetLabel", () => {
  const preset = {
    id: "warm_sun",
    name: { "zh-CN": "暖阳", en: "Warm Sun" },
    description: { "zh-CN": "温柔治愈", en: "Gentle" },
    prompt: "p",
  };

  it("按语言取名，缺失回退 zh-CN", () => {
    expect(presetLabel(preset, "en", "name")).toBe("Warm Sun");
    expect(presetLabel(preset, "zh-CN", "description")).toBe("温柔治愈");
    expect(presetLabel(preset, "fr", "name")).toBe("暖阳");
  });
});
