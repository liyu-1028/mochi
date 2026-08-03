/**
 * WebSocketClient —— 纯传输层。
 *
 * 职责：连接 / hello 握手 / 心跳 / 断线重连。
 * 不做业务解析：握手确认后所有事件原样交给 onEvent（store 负责消费，
 * 未知 type 忽略——协议 §1.3 前向兼容规则）。
 */
import {
  COMMAND_TYPES,
  EVENT_TYPES,
  PROTOCOL_VERSION,
  createCommand,
  type ClientCommand,
  type ClientInfo,
  type ServerEvent,
} from "@mochi/protocol";

export type ConnectionStatus = "disconnected" | "connecting" | "connected";

export interface WebSocketClientOptions {
  url: string;
  clientInfo: ClientInfo;
  onEvent: (event: ServerEvent) => void;
  onStatusChange: (status: ConnectionStatus) => void;
  /** 测试注入：替代全局 WebSocket */
  WebSocketImpl?: typeof WebSocket;
  /** 重连基础延迟（ms），测试可置极小值 */
  reconnectDelayMs?: number;
}

const MAX_RECONNECT_DELAY_MS = 15_000;
const PING_INTERVAL_MS = 30_000;
/** WebSocket.OPEN 的规范值；不直接引用全局 WebSocket（Node 测试环境无此全局） */
const WS_OPEN_STATE = 1;

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private manuallyClosed = false;
  private handshaken = false;
  private reconnectDelay: number;
  private reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  private pingTimer: ReturnType<typeof setInterval> | undefined;

  constructor(private readonly opts: WebSocketClientOptions) {
    this.reconnectDelay = opts.reconnectDelayMs ?? 1_500;
  }

  connect(): void {
    this.manuallyClosed = false;
    this.openSocket();
  }

  close(): void {
    this.manuallyClosed = true;
    this.clearTimers();
    this.ws?.close();
    this.ws = null;
  }

  /** 连接未就绪时丢弃并返回 false（UI 层应在断线时禁用输入）。 */
  send(command: ClientCommand): boolean {
    if (!this.ws || this.ws.readyState !== WS_OPEN_STATE) return false;
    this.ws.send(JSON.stringify(command));
    return true;
  }

  private openSocket(): void {
    const WS = this.opts.WebSocketImpl ?? WebSocket;
    this.opts.onStatusChange("connecting");
    const ws = new WS(this.opts.url);
    this.ws = ws;
    ws.onopen = () => this.sendHello();
    ws.onmessage = (ev: MessageEvent) => this.handleMessage(String(ev.data));
    ws.onclose = () => this.handleClose();
  }

  private sendHello(): void {
    this.send(
      createCommand(COMMAND_TYPES.Hello, {
        versions: [PROTOCOL_VERSION],
        client: this.opts.clientInfo,
      }),
    );
  }

  private handleMessage(raw: string): void {
    let frame: ServerEvent;
    try {
      frame = JSON.parse(raw) as ServerEvent;
    } catch {
      return; // 非法 JSON 静默丢弃
    }

    switch (frame.type) {
      case EVENT_TYPES.HelloAck:
        this.handshaken = true;
        this.reconnectDelay = this.opts.reconnectDelayMs ?? 1_500;
        this.opts.onStatusChange("connected");
        this.startPing();
        return;
      case EVENT_TYPES.HelloError:
        // 协议版本不兼容：重连无意义，交由 UI 提示升级
        this.manuallyClosed = true;
        this.opts.onStatusChange("disconnected");
        this.opts.onEvent(frame);
        return;
      case EVENT_TYPES.Pong:
        return;
      default:
        // 握手完成前的杂散事件忽略；未知 type 交由 store 按前向兼容规则忽略
        if (this.handshaken) this.opts.onEvent(frame);
    }
  }

  private handleClose(): void {
    this.clearTimers();
    const wasActive = this.handshaken;
    this.handshaken = false;
    this.ws = null;
    this.opts.onStatusChange("disconnected");
    if (this.manuallyClosed) return;
    // 指数退避重连
    const delay = this.reconnectDelay;
    this.reconnectDelay = Math.min(delay * 2, MAX_RECONNECT_DELAY_MS);
    this.reconnectTimer = setTimeout(() => this.openSocket(), delay);
    void wasActive;
  }

  private startPing(): void {
    this.pingTimer = setInterval(() => {
      this.send(createCommand(COMMAND_TYPES.Ping, { token: String(Date.now()) }));
    }, PING_INTERVAL_MS);
  }

  private clearTimers(): void {
    if (this.pingTimer !== undefined) clearInterval(this.pingTimer);
    if (this.reconnectTimer !== undefined) clearTimeout(this.reconnectTimer);
    this.pingTimer = undefined;
    this.reconnectTimer = undefined;
  }
}
