/**
 * openExternal —— 外部链接以系统默认浏览器打开的唯一入口。
 *
 * Tauri 桌面环境：invoke opener 插件（capabilities 已声明 opener:default，
 * 官方 scope 放行 http/https）；浏览器环境（dev:web）降级 window.open。
 * 仅接受 http(s) 协议——模型输出的链接不可信，禁止 file:/javascript: 等
 * 协议借道本地打开能力（测试报告 2026-08-06 问题 1：链接 URL 丢失）。
 */

/** 纯函数：判断 href 是否为安全外链（仅 http/https）。 */
export function isSafeExternalUrl(href: string): boolean {
  try {
    const { protocol } = new URL(href);
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

/** 以系统默认浏览器打开外链；不安全或非浏览器环境静默 no-op。 */
export async function openExternal(href: string): Promise<void> {
  if (!isSafeExternalUrl(href)) return;
  if (typeof window === "undefined") return;
  try {
    if ("__TAURI_INTERNALS__" in window) {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("plugin:opener|open_url", { url: href });
    } else {
      window.open(href, "_blank", "noopener,noreferrer");
    }
  } catch (err) {
    console.warn("[mochi] 打开外链失败:", href, err);
  }
}
