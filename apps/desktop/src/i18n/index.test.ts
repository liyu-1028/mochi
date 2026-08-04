/**
 * i18n translate 纯函数测试：回退链与插值。
 */
import { describe, expect, it } from "vitest";
import { STRINGS, DEFAULT_LOCALE } from "./strings";
import { translate } from "./index";

describe("translate", () => {
  it("按当前语言取文案", () => {
    expect(translate("zh-CN", "common.save")).toBe("保存");
    expect(translate("en", "common.save")).toBe("Save");
  });

  it("当前语言缺键时回退 zh-CN", () => {
    // 人为构造：en 表缺一个 zh-CN 存在的键
    const key = "common.save";
    const original = STRINGS.en[key];
    delete STRINGS.en[key];
    try {
      expect(translate("en", key)).toBe(STRINGS[DEFAULT_LOCALE][key]);
    } finally {
      STRINGS.en[key] = original;
    }
  });

  it("两种语言都缺键时回退键本身", () => {
    expect(translate("en", "no.such.key")).toBe("no.such.key");
    expect(translate("zh-CN", "no.such.key")).toBe("no.such.key");
  });

  it("{name} 占位符插值", () => {
    expect(translate("zh-CN", "settings.addedFeedback", { name: "云端" })).toBe("已添加「云端」");
    expect(translate("en", "settings.testOk", { id: "ollama" })).toBe("“ollama” connected ✓");
  });

  it("无 vars 时保留占位符原文", () => {
    expect(translate("zh-CN", "settings.addedFeedback")).toBe("已添加「{name}」");
  });

  it("zh-CN 与 en 键集合一致（防漏译）", () => {
    const zhKeys = Object.keys(STRINGS["zh-CN"]).sort();
    const enKeys = Object.keys(STRINGS.en).sort();
    expect(enKeys).toEqual(zhKeys);
  });
});
