/**
 * 分句规则（M-C，协议规范 §5.6 character.cue 的配套约定）。
 *
 * 与服务端 cue_extractor 的生成侧规则一致（docs/protocol/agent-events-v0.1.md §5.6）：
 * 终止符 `。！？!?；;` 与换行；连续终止符折叠为一个边界。
 * cueScheduler 据此把 sentenceIndex 映射为播报进度时间点。
 */

export interface SentenceSpan {
  /** 句子起始字符偏移（0-based） */
  start: number;
  /** 句子结束偏移（不含终止符） */
  end: number;
}

const TERMINATORS = new Set(["。", "！", "？", "!", "?", "；", ";", "\n"]);

/**
 * 把全文切分为句子片段（不含终止符本身）。
 * 句子 = 相邻终止符（折叠）之间的文本段；末尾无终止符的残余也是一句。
 * 空白段保留（保证 start/end 与原文偏移一致，供时长按字符数比例估算）。
 */
export function splitSentences(text: string): SentenceSpan[] {
  const spans: SentenceSpan[] = [];
  let start = 0;
  let i = 0;
  let prevBoundary = false;
  while (i < text.length) {
    const isTerm = TERMINATORS.has(text[i]);
    if (isTerm && !prevBoundary) {
      spans.push({ start, end: i });
      start = i + 1;
    }
    prevBoundary = isTerm;
    i += 1;
  }
  if (start < text.length) spans.push({ start, end: text.length });
  return spans;
}

/**
 * 各句的播报开始时间点（ms，相对播报起点）。
 * 无真实音频时长时按字符数估算（fallback 引擎）：180ms/字符，下限 1.2s。
 * 单句/空文本 → [0]（speech_start 与第 1 句重合）。
 */
export function sentenceStartTimes(text: string, durationMs: number | null): number[] {
  const spans = splitSentences(text);
  if (spans.length === 0) return [0];
  const total = durationMs ?? Math.max(1200, Math.round(text.length * 180));
  const totalChars = Math.max(1, text.length);
  return spans.map((s) => Math.round((s.start / totalChars) * total));
}
