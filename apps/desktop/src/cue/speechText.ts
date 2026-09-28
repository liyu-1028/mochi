/**
 * speechText —— TTS 朗读文本净化（M-F 补丁）。
 *
 * 问题：模型回复是 markdown（`**加粗**`、`[链接](url)` 等），气泡经
 * react-markdown 正常渲染，但 TTS 拿到的是原始文本——`**` 被语音引擎
 * 读成「星号星号」。借鉴 Open-LLM-VTuber `tts_preprocessor.tts_filter`
 * 的思路：展示与朗读分离，播报前剥离格式符号、只留可读内容。
 *
 * 原则：只剥符号、不删内容（加粗/斜体/行内代码的正文照读）；
 * 链接只读文字不读 URL；图片整体丢弃；舞台指示（（眨眨眼））在此一并剥离
 * （stripStageDirections，口径见 stageDirections.ts）。
 */

import { stripStageDirections } from "./stageDirections";

/** markdown 格式 → 朗读文本的替换表（顺序敏感：先链接/图片，后行内强调） */
const MARKDOWN_PATTERNS: ReadonlyArray<readonly [RegExp, string]> = [
  [/<https?:\/\/[^>\s]+>/g, ""], // 尖括号自动链接：整段丢弃
  [/!\[([^\]]*)\]\([^)\s]*\)/g, ""], // 图片：整体丢弃（alt 多为文件名噪音）
  [/\[([^\]]*)\]\([^)\s]*\)/g, "$1"], // 链接：只留文字
  [/\*{1,3}([^*\n]+?)\*{1,3}/g, "$1"], // 加粗/斜体/加粗斜体（**x**、*x*、***x***）
  [/(?<![\w\\])_{1,2}([^_\n]+?)_{1,2}(?![\w])/g, "$1"], // 下划线强调（__x__、_x_）
  [/~~([^~\n]+?)~~/g, "$1"], // 删除线：内容照读
  [/`{3,}[a-zA-Z0-9]*\n?/g, ""], // 代码围栏：只去围栏行，代码内容照常
  [/`([^`\n]+)`/g, "$1"], // 行内代码：去反引号
  [/^#{1,6}\s+/gm, ""], // 标题：去井号
  [/^>\s?/gm, ""], // 引用：去尖括号
  [/^\s*[-*+]\s+/gm, ""], // 无序列表符号：去减号/星号前缀
  [/^\s*(-{3,}|\*{3,}|_{3,})\s*$/gm, ""], // 水平分割线：整行丢弃
];

/** 残留的孤立格式符号（未配对的星号/反引号/波浪线）——避免被读成「星号」 */
const STRAY_SYMBOLS = /\*+|`+|~{2,}/g;

/** TTS 净化主入口：舞台指示剥离 + markdown 格式剥离。幂等。 */
export function sanitizeSpeechText(text: string): string {
  let out = stripStageDirections(text);
  for (const [pattern, replacement] of MARKDOWN_PATTERNS) {
    out = out.replace(pattern, replacement);
  }
  return out.replace(STRAY_SYMBOLS, "").replace(/[ \t]+\n/g, "\n");
}
