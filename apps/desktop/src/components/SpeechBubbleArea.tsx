/**
 * SpeechBubbleArea —— 角色头部侧向贴近的浮动对话气泡栈（屏上最多两条）。
 *
 * 栈策略：[上一条回复的折叠预览] + [最新回复全文]，更早的回复不渲染
 * （历史回顾见 HistoryPanel）。上一条半透明、只显示前两行，点击展开全文
 * （bubble--prev/bubble--expanded）；尾三角只挂在最新一条（:last-child）。
 *
 * 生命周期（区域级状态；取代旧的每气泡自治——容器坍缩/扩张捕获光标时
 * hover 联动会让已隐藏的旧气泡幽灵重现，堆叠非常高）：
 * - 新回复到来（latest.id 变化）→ 整栈重新出现，上一条展开态重置为收起
 * - 阅读估算超时（computeHideDelay，随流式文本增长重置）→ 整栈一起隐藏
 * - 悬停气泡区 → 整栈显示并暂停计时；离开恢复计时
 * - 点击折叠预览 → 展开全文，计时按展开内容长度重算；再点 → 收回两行
 *
 * 位置：渲染在角色图层之上（z-index 高于画布）、屏幕空间更充足的头部一侧——
 * useBubbleSide 按窗口在屏幕的位置选边（屏幕左半→头右侧，屏幕右半→头
 * 左侧），尾三角水平指向头部，表示「Mochi 说的话」。容器放在 .app__stage
 * 之外，避免气泡点击误触发 Tauri 窗口拖动。
 */
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useBubbleSide } from "../hooks/useBubbleSide";
import { useConversation } from "../store/conversation";
import type { ChatMessage } from "../store/conversation";
import { MarkdownBody } from "./MarkdownBody";

/** 阅读延迟估算（中文 ~5–7 字/秒 + 起始缓冲 + 上限封顶） */
export function computeHideDelay(text: string): number {
  const base = 2000;
  const perChar = 150;
  const max = 15000;
  return Math.min(base + text.length * perChar, max);
}

export interface BubbleStack {
  prev?: ChatMessage;
  latest?: ChatMessage;
}

/** 纯函数便于单测：assistant 消息（不含历史回显）取最后两条，prev=倒数第二。 */
export function pickBubbleStack(messages: ChatMessage[]): BubbleStack {
  const visible = messages.filter((m) => m.role === "assistant" && !m.fromHistory);
  if (visible.length === 0) return {};
  return {
    prev: visible.length > 1 ? visible[visible.length - 2] : undefined,
    latest: visible[visible.length - 1],
  };
}

export function SpeechBubbleArea() {
  const messages = useConversation((s) => s.messages);
  const { prev, latest } = pickBubbleStack(messages);
  const side = useBubbleSide();
  const [hidden, setHidden] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const latestId = latest?.id;
  const latestText = latest?.text;
  const prevId = prev?.id;
  const prevText = prev?.text;

  // 新回复到来 → 整栈重新出现（覆盖超时隐藏态）
  useEffect(() => {
    if (latestId !== undefined) setHidden(false);
  }, [latestId]);

  // 换了新的上一条 → 重置收起态，避免新预览自动以展开态出现
  useEffect(() => {
    setExpanded(false);
  }, [prevId]);

  // 整栈自动隐藏计时：hover → 显示不计时；展开时按展开内容长度重算延迟
  // （想久读可悬停暂停，与既有语义一致）；流式文本增长经 latestText 重置
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    if (latestId === undefined || hovered) return;
    const delay = computeHideDelay(
      expanded && prevText !== undefined ? prevText : (latestText ?? ""),
    );
    timerRef.current = setTimeout(() => setHidden(true), delay);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = null;
    };
  }, [latestId, latestText, prevText, hovered, expanded]);

  return (
    <div
      className={`bubbles bubbles--${side}${hidden || latest === undefined ? " bubbles--hidden" : ""}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {prev !== undefined ? (
        <PrevBubble message={prev} expanded={expanded} onToggle={() => setExpanded((v) => !v)} />
      ) : null}
      {latest !== undefined ? <CurrentBubble message={latest} /> : null}
    </div>
  );
}

/** 上一条回复：折叠预览（两行、半透明），点击/键盘展开全文 */
function PrevBubble({
  message,
  expanded,
  onToggle,
}: {
  message: ChatMessage;
  expanded: boolean;
  onToggle: () => void;
}) {
  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onToggle();
    }
  };
  return (
    <div
      className={`bubble bubble--prev${expanded ? " bubble--expanded" : ""}`}
      role="button"
      tabIndex={0}
      aria-expanded={expanded}
      onClick={onToggle}
      onKeyDown={handleKeyDown}
    >
      <div className="bubble__body">
        {message.text ? <MarkdownBody text={message.text} /> : null}
      </div>
    </div>
  );
}

/** 最新回复：全文展示 + 流式光标 */
function CurrentBubble({ message }: { message: ChatMessage }) {
  return (
    <div className="bubble">
      <div className="bubble__body">
        {message.text ? <MarkdownBody text={message.text} /> : message.streaming && "…"}
        {message.streaming && message.text ? <span className="bubble__cursor">▍</span> : null}
      </div>
    </div>
  );
}
