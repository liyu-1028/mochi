import { describe, expect, it } from "vitest";
import { sanitizeSpeechText } from "./speechText";

describe("sanitizeSpeechText (严厉压力测试与边界测试)", () => {
  it("空文本与纯空白字符处理", () => {
    expect(sanitizeSpeechText("")).toBe("");
    expect(sanitizeSpeechText("   \n\t  ").trim()).toBe("");
  });

  it("纯格式或纯舞台指示：过滤后为空或纯空白", () => {
    expect(sanitizeSpeechText("****").trim()).toBe("");
    expect(sanitizeSpeechText("（眨眼）").trim()).toBe("");
    expect(sanitizeSpeechText("（眨眼）（点头）（微笑）").trim()).toBe("");
    expect(sanitizeSpeechText("**（眨眨眼）**~~（点头）~~").trim()).toBe("");
  });

  it("深度嵌套的 markdown 强调与符号组合", () => {
    // 粗体包含斜体包含删除线
    expect(sanitizeSpeechText("**粗体 *斜体 ~~删除~~* 结束**")).toBe("粗体 斜体 删除 结束");
    // 反引号代码块与加粗组合
    expect(sanitizeSpeechText("**运行 `npm test` 看看**")).toBe("运行 npm test 看看");
  });

  it("多行代码围栏与行内代码混合", () => {
    const input = [
      "请按照如下命令操作：",
      "```bash",
      "echo 'hello world'",
      "npm run dev",
      "```",
      "然后查看效果。",
    ].join("\n");
    const output = sanitizeSpeechText(input);
    expect(output).toContain("echo 'hello world'");
    expect(output).toContain("npm run dev");
    expect(output).not.toContain("```");
  });

  it("各种边界链接与图片语法", () => {
    // 空链接文本
    expect(sanitizeSpeechText("看 [](https://example.com) 这里")).toBe("看  这里");
    // 多图片混杂
    expect(sanitizeSpeechText("![alt1](a.png)文字![alt2](b.jpg)")).toBe("文字");
    // 尖括号自动链接
    expect(sanitizeSpeechText("访问 <https://mochi.ai> 获取详情")).toBe("访问  获取详情");
  });

  it("混合中英文、Emoji 与全半角括号", () => {
    const text = "Hello 🐱! (数学公式 x+y) （动作眨眼） ✨ 真的很棒！";
    const result = sanitizeSpeechText(text);
    // 半角括号 (数学公式 x+y) 保留，全角舞台指示 （动作眨眼） 剥离
    expect(result).toContain("(数学公式 x+y)");
    expect(result).not.toContain("动作眨眼");
    expect(result).toContain("🐱");
    expect(result).toContain("✨");
  });

  it("大量未配对的杂乱符号不崩溃且被清洗", () => {
    const dirty = "***你好```世界~~~!*`~~*";
    const cleaned = sanitizeSpeechText(dirty);
    expect(cleaned).toBe("你好世界~!");
    expect(cleaned).not.toContain("*");
    expect(cleaned).not.toContain("`");
    expect(cleaned).not.toContain("~~");
  });
});
