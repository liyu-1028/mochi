/**
 * sidecarRuntime 纯内核测试：负载校验、端口订阅、默认值。
 * Tauri 事件监听本身不在单测范围（node 环境无 runtime）。
 */
import { describe, expect, it } from "vitest";
import {
  DEFAULT_SIDECAR_PORT,
  extractReadyPort,
  getRuntimePort,
  SIDECAR_READY_EVENT,
  subscribeRuntimePort,
} from "./sidecarRuntime";

describe("extractReadyPort", () => {
  it("提取合法端口", () => {
    expect(extractReadyPort({ port: 8199 })).toBe(8199);
    expect(extractReadyPort({ port: 9321 })).toBe(9321);
  });

  it("拒绝非法负载", () => {
    expect(extractReadyPort(null)).toBeNull();
    expect(extractReadyPort(undefined)).toBeNull();
    expect(extractReadyPort("8199")).toBeNull();
    expect(extractReadyPort({})).toBeNull();
    expect(extractReadyPort({ port: "8199" })).toBeNull();
    expect(extractReadyPort({ port: -1 })).toBeNull();
    expect(extractReadyPort({ port: 0 })).toBeNull();
    expect(extractReadyPort({ port: 81.99 })).toBeNull();
  });
});

describe("runtime port state", () => {
  it("默认端口为 8199，事件名与 Rust 侧约定一致", () => {
    expect(DEFAULT_SIDECAR_PORT).toBe(8199);
    expect(SIDECAR_READY_EVENT).toBe("mochi://sidecar-ready");
  });

  it("未收到就绪事件时端口为 null（调用方退回默认）", () => {
    expect(getRuntimePort()).toBeNull();
  });

  it("订阅返回可用的取消函数", () => {
    const unsubscribe = subscribeRuntimePort(() => undefined);
    expect(typeof unsubscribe).toBe("function");
    unsubscribe();
  });
});
