/**
 * MarkdownBody —— 轻量 Markdown 渲染（M1-S1，功能清单 4.1）。
 *
 * react-markdown + remark-gfm 支持加粗/列表/行内代码/表格等常见语法；
 * 代码块降级为纯 <pre>（不引入高亮库）、链接降级为纯文本（防 webview 跳转）。
 * 气泡与聊天回忆面板共用（M1-CTX 提取为独立组件）。
 */
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ComponentPropsWithoutRef } from "react";

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

export function MarkdownBody({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
      {text}
    </ReactMarkdown>
  );
}
