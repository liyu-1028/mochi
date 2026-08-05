/**
 * sidecar 运行时端口发现（M1-S0）。
 *
 * release 模式桌面壳轮询 runtime.json，读到后 emit
 * `mochi://sidecar-ready {port}`（src-tauri/src/runtime.rs）；
 * 前端 REST/WS 地址据此切换到实际端口。dev/Web 环境无事件源：
 * 退回默认 8199；VITE_API_URL / VITE_WS_URL 覆盖优先级最高（保持 dev 体验）。
 */
import { listen } from "@tauri-apps/api/event";

export const SIDECAR_READY_EVENT = "mochi://sidecar-ready";

export const DEFAULT_SIDECAR_PORT = 8199;

type PortListener = (port: number) => void;

let runtimePort: number | null = null;
let initialized = false;
const listeners = new Set<PortListener>();

/** 是否运行于 Tauri 桌面 runtime（node 测试环境无 window）。 */
const IS_TAURI = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

/** 当前发现的运行时端口；null = 未收到就绪事件，走默认端口。 */
export function getRuntimePort(): number | null {
  return runtimePort;
}

/** 订阅端口更新；返回取消订阅函数。 */
export function subscribeRuntimePort(listener: PortListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** 校验就绪事件负载并提取端口；非法负载返回 null（保持默认端口）。 */
export function extractReadyPort(payload: unknown): number | null {
  if (typeof payload !== "object" || payload === null) return null;
  const port = (payload as { port?: unknown }).port;
  return typeof port === "number" && Number.isInteger(port) && port > 0 ? port : null;
}

/** 挂监听（幂等）；非 Tauri 环境直接 no-op。 */
export function initRuntimePortListener(): void {
  if (initialized || !IS_TAURI) return;
  initialized = true;
  void listen<unknown>(SIDECAR_READY_EVENT, (event) => {
    const port = extractReadyPort(event.payload);
    if (port === null || port === runtimePort) return;
    runtimePort = port;
    listeners.forEach((fn) => fn(port));
  });
}
