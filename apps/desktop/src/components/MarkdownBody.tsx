/**
 * MarkdownBody —— 轻量 Markdown 渲染（M1-S1，功能清单 4.1）。
 *
 * react-markdown + remark-gfm 支持加粗/列表/行内代码/表格等常见语法；
 * 代码块降级为纯 <pre>（不引入高亮库）。
 * 链接保留 href：点击经 openExternal 交系统默认浏览器打开（仍不在 webview
 * 内跳转），悬停 title 可见目标 URL——修复 URL 被彻底剥离的信息丢失
 * （测试报告 2026-08-06 问题 1）。
 * 气泡与聊天回忆面板共用（M1-CTX 提取为独立组件）。
 */
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ComponentPropsWithoutRef } from "react";
import { openExternal } from "../openExternal";

const MARKDOWN_COMPONENTS = {
  pre: ({ children }: ComponentPropsWithoutRef<"pre">) => (
    <pre className="bubble__pre">{children}</pre>
  ),
  code: ({ children }: ComponentPropsWithoutRef<"code">) => (
    <code className="bubble__code">{children}</code>
  ),
  a: ({ children, href }: ComponentPropsWithoutRef<"a">) => (
    <span
      className="bubble__link"
      role="link"
      tabIndex={0}
      title={href}
      onClick={() => href && void openExternal(href)}
      onKeyDown={(e) => {
        if (href && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          void openExternal(href);
        }
      }}
    >
      {children}
    </span>
  ),
};

export function MarkdownBody({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
      {text}
    </ReactMarkdown>
  );
}
