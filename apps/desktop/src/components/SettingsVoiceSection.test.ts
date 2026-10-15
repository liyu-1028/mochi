/** 语音设置组件纯函数测试（node 环境直测，仓库惯例）。 */
import { describe, expect, it } from "vitest";
import type { ReactElement } from "react";
import { buildSetupInput, renderVoiceOptions } from "./SettingsVoiceSection";
import type { TtsVoiceOption } from "../api/ttsClient";

/** renderVoiceOptions 产物统一按 JSX 元素断言（node 环境零 DOM）。 */
const elements = (opts: TtsVoiceOption[], t: (key: string) => string) =>
  renderVoiceOptions(opts, t) as ReactElement<{ label?: string; children?: unknown }>[];

describe("buildSetupInput", () => {
  it("复用连接优先于新 Key", () => {
    expect(buildSetupInput("sk-new", "cloud")).toEqual({ reuseConnectionId: "cloud" });
  });
  it("仅 Key 时走新录", () => {
    expect(buildSetupInput("sk-new", "")).toEqual({ apiKey: "sk-new" });
  });
  it("两者皆空 → null（禁用态）", () => {
    expect(buildSetupInput("", "")).toBeNull();
  });
});

describe("renderVoiceOptions", () => {
  const t = (key: string) => `[${key}]`;
  const companion: TtsVoiceOption = {
    id: "longxing_v3",
    name: "龙星 · 温婉邻家女",
    lang: "zh-CN",
    gender: "female",
    category: "companion",
  };
  const dialect: TtsVoiceOption = {
    id: "longlaotie_v3",
    name: "龙老铁 · 东北男",
    lang: "zh-CN",
    gender: "male",
    category: "dialect",
  };
  const plain: TtsVoiceOption = { id: "mix_1", name: "mix_1", lang: "", gender: "" };

  it("同品类合并进 optgroup，label 走 i18n 键", () => {
    const nodes = elements([companion, dialect, companion], t);
    const groups = nodes.filter((n) => n.type === "optgroup");
    expect(groups).toHaveLength(2);
    expect(groups[0].props.label).toBe("[voice.category.companion]");
    expect(groups[0].props.children).toHaveLength(2); // 两个 companion 合并
  });

  it("无 category 平铺为 option，排在分组之后", () => {
    const nodes = elements([plain, companion], t);
    expect(nodes[0].type).toBe("optgroup");
    expect(nodes[1].type).toBe("option");
    expect(nodes[1].props.children).toBe("mix_1");
  });

  it("zh-CN 不加后缀，非中文语言追加（en-US）", () => {
    const en: TtsVoiceOption = {
      id: "loong_1",
      name: "Bella",
      lang: "en-US",
      gender: "female",
    };
    const [opt] = elements([en], t);
    expect(opt.props.children).toBe("Bella（en-US）");
  });
});
