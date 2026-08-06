/**
 * useSidecarStatus —— 监听 Rust 侧 sidecar 生命周期事件（M0-S4，功能清单 1.2）。
 *
 * release 模式下 sidecar 异常退出/重启/启动失败由监督线程发
 * `mochi://sidecar-status` 事件；此钩子把 failed/restarting 翻译成
 * 页脚可读提示（「用户全程不接触终端」验收）。浏览器环境无 Tauri 运行时，
 * 直接返回 null（dev 下 sidecar 异常由 WS 重连状态呈现）。
 *
 * Tauri API 走静态导入（包内其他模块已静态引入 event，动态导入无代码
 * 分割收益，vite 会告警）；浏览器环境隔离由运行时守卫承担。
 */
import { listen } from "@tauri-apps/api/event";
import { useEffect, useState } from "react";

interface SidecarStatusPayload {
  status: "started" | "restarting" | "failed";
  detail: string;
}

/** 返回需要覆盖连接状态展示的提示文案；null 表示无覆盖。 */
export function useSidecarStatus(): string | null {
  const [hint, setHint] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) return;
    let unlisten: (() => void) | null = null;
    let cancelled = false;

    void listen<SidecarStatusPayload>("mochi://sidecar-status", (e) => {
      const { status, detail } = e.payload;
      if (status === "failed") setHint(detail || "后端服务启动失败，请重启 Mochi");
      else if (status === "restarting") setHint(detail || "后端服务重启中…");
      else setHint(null); // started：恢复正常连接状态展示
    }).then((u) => {
      if (cancelled) u();
      else unlisten = u;
    });

    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  return hint;
}
