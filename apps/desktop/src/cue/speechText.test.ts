/**
 * speechText（M-F 补丁）测试：markdown 格式符号不进 TTS。
 *
 * 背景：语音引擎把原始 `**` 读成「星号星号」——播报前必须净化，
 * 气泡渲染（react-markdown）不受影响。原则：只剥符号、不删内容。
 */
import { describe, expect, it } from "vitest";
import { sanitizeSpeechText } from "./speechText";

describe("sanitizeSpeechText：markdown 格式剥离", () => {
  it("加粗：剥星号、留正文（回归：不再读出「星号星号」）", () => {
    expect(sanitizeSpeechText("**非常**不好笑")).toBe("非常不好笑");
    expect(sanitizeSpeechText("这是**加粗**和__下划线粗体__")).toBe("这是加粗和下划线粗体");
  });

  it("斜体/删除线：剥符号留正文", () => {
    expect(sanitizeSpeechText("*轻声*你好")).toBe("轻声你好");
    expect(sanitizeSpeechText("~~旧方案~~新方案")).toBe("旧方案新方案");
  });

  it("链接只读文字，URL 不进语音；图片丢弃", () => {
    expect(sanitizeSpeechText("看[文档](https://example.com/a)即可")).toBe("看文档即可");
    expect(sanitizeSpeechText("![截图](https://example.com/x.png)如上")).toBe("如上");
  });

  it("代码：行内去反引号，围栏去围栏行但保留内容", () => {
    expect(sanitizeSpeechText("运行 `pnpm dev` 即可")).toBe("运行 pnpm dev 即可");
    const fenced = sanitizeSpeechText("步骤：\n```bash\npnpm dev\n```\n完成");
    expect(fenced).toContain("pnpm dev");
    expect(fenced).not.toContain("```");
  });

  it("标题/引用/列表符号/分割线", () => {
    expect(sanitizeSpeechText("## 总结\n内容")).toBe("总结\n内容");
    expect(sanitizeSpeechText("> 引用一句话")).toBe("引用一句话");
    expect(sanitizeSpeechText("- 第一条\n- 第二条")).toBe("第一条\n第二条");
    expect(sanitizeSpeechText("上文\n---\n下文")).toBe("上文\n\n下文");
  });

  it("残留未配对符号也被清除（否则仍会读出星号）", () => {
    expect(sanitizeSpeechText("奇怪*的输入")).toBe("奇怪的输入");
    expect(sanitizeSpeechText("嗯`")).toBe("嗯");
  });

  it("幂等", () => {
    const once = sanitizeSpeechText("**粗**与（眨眨眼）与 `code`");
    expect(sanitizeSpeechText(once)).toBe(once);
  });

  it("与舞台指示剥离叠加：纯格式/纯指示的文本播报为空（调用方跳过合成）", () => {
    expect(sanitizeSpeechText("**（眨眨眼）**").trim()).toBe("");
  });

  it("普通文本与数学减号不受影响", () => {
    expect(sanitizeSpeechText("普通的一句话。")).toBe("普通的一句话。");
    expect(sanitizeSpeechText("3 - 1 = 2")).toBe("3 - 1 = 2");
  });
});
