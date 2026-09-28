/**
 * stageDirections —— 中文舞台指示的 TTS 剥离（M-F）。
 *
 * 调研依据（Open-LLM-VTuber `tts_preprocessor.tts_filter` 的括号过滤 +
 * `think_tag_prompt` 的「动作描写不进 TTS」实践）：人格用全角括号写的
 * 舞台指示（（眨眨眼）（点头））保留在气泡里展示，但不应被 TTS 读出来。
 *
 * 口径约定（与服务端 stage_directions.py 一致）：
 * - 只处理全角（...）——半角括号是代码/数学惯例，不碰；
 * - 成对段整段剥离；流末未闭合残段也剥离（TTS 不读残段）；
 * - 服务端分句计数同口径（cue_extractor 括号感知），sentenceIndex 对齐。
 */

/** 全角成对括号段（不含嵌套；人格书写惯例为单层） */
const DIRECTION_PAIR = /（[^（）]*）/g;
/** 流末未闭合残段（跨 chunk 截断或流被截断时） */
const DIRECTION_OPEN_TAIL = /（[^（）]*$/;

/** TTS 文本剥离舞台指示；气泡文本不走此函数。幂等。 */
export function stripStageDirections(text: string): string {
  return text.replace(DIRECTION_PAIR, "").replace(DIRECTION_OPEN_TAIL, "");
}
