/**
 * WebSocketClient 传输层测试（MockWebSocket 注入，不依赖真实网络）。
 */
import { COMMAND_TYPES, PROTOCOL_VERSION, createCommand } from "@mochi/protocol";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WebSocketClient } from "./WebSocketClient";

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static OPEN = 1;

  url: string;
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = 3;
    this.onclose?.();
  }

  // ---- 测试助手 ----
  simulateOpen(): void {
    this.readyState = 1;
    this.onopen?.();
  }

  simulateMessage(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  simulateClose(): void {
    this.readyState = 3;
    this.onclose?.();
  }
}

const MockWS = MockWebSocket as unknown as typeof WebSocket;

function makeClient(onEvent = vi.fn(), onStatusChange = vi.fn()) {
  const client = new WebSocketClient({
    url: "ws://test/ws",
    clientInfo: { name: "test", version: "0.0.0" },
    onEvent,
    onStatusChange,
    WebSocketImpl: MockWS,
    reconnectDelayMs: 10,
  });
  return { client, onEvent, onStatusChange };
}

function latest(): MockWebSocket {
  return MockWebSocket.instances[MockWebSocket.instances.length - 1];
}

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.restoreAllMocks();
});

describe("握手", () => {
  it("连接建立后立即发送 hello，携带协议版本与客户端信息", () => {
    const { client } = makeClient();
    client.connect();
    latest().simulateOpen();

    const hello = JSON.parse(latest().sent[0]);
    expect(hello.type).toBe("hello");
    expect(hello.v).toBe(PROTOCOL_VERSION);
    expect(hello.data.versions).toContain(PROTOCOL_VERSION);
    expect(hello.data.client).toEqual({ name: "test", version: "0.0.0" });
  });

  it("hello_ack → 状态 connected", () => {
    const { client, onStatusChange } = makeClient();
    client.connect();
    latest().simulateOpen();
    latest().simulateMessage({ type: "hello_ack", v: "0.1", id: "s1", ts: 0, data: {} });

    expect(onStatusChange).toHaveBeenLastCalledWith("connected");
  });

  it("hello_error → 状态 disconnected 且不重连（版本不兼容重连无意义）", () => {
    const { client, onEvent, onStatusChange } = makeClient();
    client.connect();
    const ws = latest();
    ws.simulateOpen();
    ws.simulateMessage({
      type: "hello_error",
      v: "0.1",
      id: "s1",
      ts: 0,
      data: { error: { code: "ERR_VERSION_MISMATCH", message: "x", retryable: false } },
    });

    expect(onStatusChange).toHaveBeenLastCalledWith("disconnected");
    expect(onEvent).toHaveBeenCalledTimes(1); // 交由 UI 提示升级
    ws.simulateClose(); // 即便连接关闭也不应触发重连
    expect(MockWebSocket.instances).toHaveLength(1);
  });
});

describe("事件分发", () => {
  function connected(onEvent: ReturnType<typeof vi.fn>) {
    const { client } = makeClient(onEvent);
    client.connect();
    latest().simulateOpen();
    latest().simulateMessage({ type: "hello_ack", v: "0.1", id: "s1", ts: 0, data: {} });
    return latest();
  }

  it("握手后的业务事件原样分发", () => {
    const onEvent = vi.fn();
    const ws = connected(onEvent);
    const frame = { type: "text.delta", v: "0.1", id: "s2", ts: 0, data: { delta: "你好" } };
    ws.simulateMessage(frame);

    expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ type: "text.delta" }));
  });

  it("未知 type 依然分发（前向兼容：由 store 忽略）", () => {
    const onEvent = vi.fn();
    const ws = connected(onEvent);
    ws.simulateMessage({ type: "future.event", v: "0.1", id: "s3", ts: 0, data: {} });

    expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ type: "future.event" }));
  });

  it("握手完成前不派发业务事件；非法 JSON 静默丢弃", () => {
    const onEvent = vi.fn();
    const { client } = makeClient(onEvent);
    client.connect();
    const ws = latest();
    ws.simulateOpen();
    ws.simulateMessage({ type: "text.delta", v: "0.1", id: "s2", ts: 0, data: {} });
    ws.onmessage?.({ data: "{not-json" });

    expect(onEvent).not.toHaveBeenCalled();
  });
});

describe("重连", () => {
  it("非主动断开后自动重连（新建连接并重新握手）", async () => {
    vi.useFakeTimers();
    try {
      const { client, onStatusChange } = makeClient();
      client.connect();
      latest().simulateOpen();
      latest().simulateMessage({ type: "hello_ack", v: "0.1", id: "s1", ts: 0, data: {} });

      latest().simulateClose();
      expect(onStatusChange).toHaveBeenLastCalledWith("disconnected");
      expect(MockWebSocket.instances).toHaveLength(1);

      await vi.advanceTimersByTimeAsync(20);
      expect(MockWebSocket.instances).toHaveLength(2); // 已发起重连
    } finally {
      vi.useRealTimers();
    }
  });

  it("close() 为主动断开，不重连", async () => {
    vi.useFakeTimers();
    try {
      const { client } = makeClient();
      client.connect();
      latest().simulateOpen();
      client.close();

      await vi.advanceTimersByTimeAsync(1000);
      expect(MockWebSocket.instances).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("未就绪时 send 返回 false", () => {
    const { client } = makeClient();
    client.connect(); // 未 open
    const ok = client.send(createCommand(COMMAND_TYPES.Ping, { token: "t" }));
    expect(ok).toBe(false);
  });
});
