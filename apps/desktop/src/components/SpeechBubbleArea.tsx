/**
 * SpeechBubbleArea —— 角色头部两侧的浮动对话气泡。
 *
 * 位置：出现在头部左侧或右侧（useBubbleSide 按窗口在屏幕上的位置
 * 自动选空间更充足的一），尾三角水平指向头部，表示「Mochi 说的话」。
 *
 * 自动隐藏 + 悬停保持方案：
 * - 每条气泡按消息字符数计算"阅读延迟"（base + 150ms/字），超时自动隐藏
 * - 鼠标悬停在气泡区时：所有气泡显示，定时器暂停
 * - 鼠标离开后：定时器重新启动，继续按延迟隐藏
 * - 流式 delta 时延迟随字符数增长（用户边看边接收新内容）
 *
 * 提示：容器放在 .app__stage 之外，避免气泡点击误触发 Tauri 窗口拖动。
 */
import { useEffect, useRef, useState, type ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useBubbleSide } from "../hooks/useBubbleSide";
import { useConversation } from "../store/conversation";
import type { ChatMessage } from "../store/conversation";

/** 阅读延迟估算（中文 ~5–7 字/秒 + 起始缓冲 + 上限封顶） */
export function computeHideDelay(text: string): number {
  const base = 2000;
  const perChar = 150;
  const max = 15000;
  return Math.min(base + text.length * perChar, max);
}

/**
 * 气泡内轻量 Markdown 渲染（M1-S1，功能清单 4.1）：
 * - react-markdown + remark-gfm 支持加粗/列表/行内代码/表格等常见语法；
 * - 代码块降级为纯 <pre>（不引入高亮库），控制窗口内的渲染开销；
 * - 链接降级为纯文本，避免点击导致 Tauri webview 跳转。
 */
const MARKDOWN_COMPONENTS = {
  pre: ({ children }: ComponentPropsWithoutRef<"pre">) => (
    <pre className="bubble__pre">{children}</pre>
  ),
  code: ({ children }: ComponentPropsWithoutRef<"code">) => (
    <code className="bubble__code">{children}</code>
  ),
  a: ({ children }: ComponentPropsWithoutRef<"a">) => (
    <span className="bubble__link">{children}</span>
  ),
};

function MarkdownBody({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
      {text}
    </ReactMarkdown>
  );
}

export function SpeechBubbleArea() {
  const messages = useConversation((s) => s.messages);
  const assistantMessages = messages.filter((m) => m.role === "assistant");
  const [hover, setHover] = useState(false);
  const side = useBubbleSide();

  return (
    <div
      className={`bubbles bubbles--${side}`}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      {assistantMessages.map((m) => (
        <SpeechBubble key={m.id} message={m} hovered={hover} />
      ))}
    </div>
  );
}

function SpeechBubble({ message, hovered }: { message: ChatMessage; hovered: boolean }) {
  const [hidden, setHidden] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // 依赖 hover 与文本：hover 状态切换或文本增长都重置定时器
    if (timerRef.current) clearTimeout(timerRef.current);
    if (hovered) {
      // 悬停期间显示且暂停定时器
      setHidden(false);
      return;
    }
    timerRef.current = setTimeout(() => {
      setHidden(true);
    }, computeHideDelay(message.text));
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [message.text, hovered]);

  return (
    <div className={`bubble ${hidden ? "bubble--hidden" : ""}`}>
      <div className="bubble__body">
        {message.text ? <MarkdownBody text={message.text} /> : message.streaming && "…"}
        {message.streaming && message.text ? <span className="bubble__cursor">▍</span> : null}
      </div>
      <span className="bubble__tail" aria-hidden />
    </div>
  );
}
