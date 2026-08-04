/**
 * configClient —— sidecar REST 管理端点的 fetch 封装（ADR-0002 D3）。
 *
 * Key 只在 create/update 时单向提交，服务端落钥匙串；
 * 响应中永无明文 Key，只有 keyRef + maskedKey。
 */
import type { Language } from "../i18n/strings";

export type ProviderKind = "ollama" | "openai_compatible" | "anthropic";

/** [general] 设置视图（config-format.md）；界面语言为 M1-CTX 设置项。 */
export interface GeneralSettings {
  language: Language;
  launchAtStartup: boolean;
  telemetry: boolean;
}

export interface ProviderSummary {
  id: string;
  kind: ProviderKind;
  displayName: string;
  baseUrl?: string;
  model: string;
  keyRef?: string;
  maskedKey?: string;
  isDefault: boolean;
}

export interface OllamaStatus {
  available: boolean;
  models: string[];
  errorHint?: string;
}

export interface ProviderTestResult {
  ok: boolean;
  hint?: string;
}

export interface ProviderCreateInput {
  id: string;
  kind: ProviderKind;
  displayName: string;
  baseUrl?: string;
  model: string;
  apiKey?: string;
}

export const TRIAL_PROVIDER_ID = "trial";

/** sidecar REST 地址：dev 手动起 sidecar（默认 8199），可用 VITE_API_URL 覆盖。 */
export function resolveHttpBaseUrl(): string {
  return import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8199";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${resolveHttpBaseUrl()}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let detail: unknown = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? resp.statusText;
    } catch {
      // 非 JSON 错误体：保留 statusText
    }
    throw new Error(typeof detail === "string" ? detail : "请求失败");
  }
  if (resp.status === 204) {
    return undefined as T;
  }
  return resp.json() as Promise<T>;
}

export const configApi = {
  /** 完整配置（含 general.language）；此处只声明前端关心的 general 段。 */
  getConfig: (): Promise<{ general: GeneralSettings }> => request("/config"),

  /** 部分更新 [general]（界面语言），返回更新后的 general。 */
  updateGeneral: (body: { language?: Language }): Promise<GeneralSettings> =>
    request("/config/general", { method: "PUT", body: JSON.stringify(body) }),

  listProviders: (): Promise<ProviderSummary[]> => request("/config/providers"),

  createProvider: (body: ProviderCreateInput): Promise<ProviderSummary> =>
    request("/config/providers", { method: "POST", body: JSON.stringify(body) }),

  deleteProvider: (id: string): Promise<void> =>
    request(`/config/providers/${encodeURIComponent(id)}`, { method: "DELETE" }),

  setDefault: (id: string): Promise<{ defaultProvider: string }> =>
    request(`/config/providers/${encodeURIComponent(id)}/default`, { method: "PUT" }),

  testProvider: (id: string): Promise<ProviderTestResult> =>
    request(`/config/providers/${encodeURIComponent(id)}/test`, { method: "POST" }),

  ollamaStatus: (): Promise<OllamaStatus> => request("/config/providers/ollama-status"),
};

// ---------------------------------------------------------------------------
// 会话历史（M1-S1，功能清单 4.3 回看面）
// ---------------------------------------------------------------------------

export interface SessionSummary {
  id: string;
  title?: string;
  createdAt: number;
  updatedAt: number;
}

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
  ts: number;
}

export const sessionApi = {
  listSessions: (): Promise<SessionSummary[]> => request("/sessions"),

  getMessages: (sessionId: string): Promise<HistoryMessage[]> =>
    request(`/sessions/${encodeURIComponent(sessionId)}/messages`),

  deleteSession: (sessionId: string): Promise<void> =>
    request(`/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),
};
