/**
 * configClient —— sidecar REST 管理端点的 fetch 封装（ADR-0002 D3）。
 *
 * Key 只在 configure 时单向提交，服务端测试成功后落钥匙串；
 * 响应中永无明文 Key，只有 keyRef + maskedKey。
 */
import type { Language } from "../i18n/strings";
import { DEFAULT_SIDECAR_PORT, getRuntimePort } from "./sidecarRuntime";

export type WireProtocol = "openai_chat" | "openai_responses" | "anthropic_messages";

/** [general] 设置视图（config-format.md）；界面语言为 M1-CTX 设置项。 */
export interface GeneralSettings {
  language: Language;
  launchAtStartup: boolean;
  telemetry: boolean;
  powerSave: boolean;
}

export interface ProviderPreset {
  id: string;
  displayName: string;
  description: string;
  authKind: "api_key" | "none";
  protocols: WireProtocol[];
  recommendedProtocol: WireProtocol;
  defaultEndpoints: Partial<Record<WireProtocol, string>>;
  modelPlaceholder: string;
  allowsCustomEndpoint: boolean;
}

export interface ModelProfileSummary {
  id: string;
  connectionId: string;
  presetId: string;
  connectionName: string;
  displayName: string;
  protocol: WireProtocol;
  baseUrl?: string;
  model: string;
  contextWindow?: number;
  keyRef?: string;
  maskedKey?: string;
  isDefault: boolean;
}

export interface OllamaStatus {
  available: boolean;
  models: string[];
  errorHint?: string;
}

export interface ModelTestResult {
  ok: boolean;
  hint?: string;
}

/** 服务端用同一份草稿先测试、成功后原子保存，避免测试态与保存态漂移。 */
export interface ModelConfigureInput {
  profileId: string;
  connectionId: string;
  presetId: string;
  connectionName: string;
  profileName: string;
  protocol: WireProtocol;
  baseUrl?: string;
  model: string;
  apiKey?: string;
  contextWindow?: number;
}

export interface ModelConfigureResult extends ModelTestResult {
  profile?: ModelProfileSummary;
}

/** [voice] 视图（M1-S0 托盘静音；S2 TTS 设置复用）。 */
export interface VoiceSettings {
  ttsEnabled: boolean;
  engine: "edge" | "local";
  voiceId: string;
  volume: number;
  rate: number;
  muted: boolean;
}

/** [character] 视图（3.3 换肤持久化；persona 有专属端点）。 */
export interface CharacterSettings {
  activeSkin: string;
}

/** 人格维度（6.13）：灵魂 / 性格 / 说话风格，与 persona.py DIMENSIONS 一致。 */
export type PersonaDimension = "soul" | "personality" | "style";

/** 单个人格预设（服务端目录为唯一事实源，ADR-0005 D1）。 */
export interface PersonaPreset {
  id: string;
  name: Record<string, string>;
  description: Record<string, string>;
  prompt: string;
}

/** [character.persona] 当前配置（camelCase 视图）。 */
export interface PersonaSettings {
  soulPreset: string;
  soulCustom: string;
  personalityPreset: string;
  personalityCustom: string;
  stylePreset: string;
  styleCustom: string;
}

/** GET /config/persona 响应：当前配置 + 三维预设目录。 */
export interface PersonaFullView {
  current: PersonaSettings;
  presets: Record<PersonaDimension, PersonaPreset[]>;
}

export const TRIAL_PROFILE_ID = "trial";

/**
 * sidecar REST 地址：VITE_API_URL 覆盖 > runtime.json 发现端口 > 默认 8199。
 * 每次调用即时读取运行时端口（发现事件晚于首屏也不丢，M1-S0 端口发现）。
 */
export function resolveHttpBaseUrl(): string {
  if (import.meta.env.VITE_API_URL) return import.meta.env.VITE_API_URL;
  return `http://127.0.0.1:${getRuntimePort() ?? DEFAULT_SIDECAR_PORT}`;
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
  /** 完整配置（含 general/character/voice 段；诊断导出与设置导入用）。 */
  getConfig: (): Promise<{
    general: GeneralSettings;
    character?: CharacterSettings;
    voice?: VoiceSettings;
  }> => request("/config"),

  /** 部分更新 [general]（界面语言/省电模式），返回更新后的 general。 */
  updateGeneral: (body: { language?: Language; powerSave?: boolean }): Promise<GeneralSettings> =>
    request("/config/general", { method: "PUT", body: JSON.stringify(body) }),

  listModelPresets: (): Promise<ProviderPreset[]> => request("/config/model-presets"),

  listModelProfiles: (): Promise<ModelProfileSummary[]> => request("/config/model-profiles"),

  configureModel: (body: ModelConfigureInput): Promise<ModelConfigureResult> =>
    request("/config/model-profiles/configure", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  deleteModelProfile: (id: string): Promise<void> =>
    request(`/config/model-profiles/${encodeURIComponent(id)}`, { method: "DELETE" }),

  deleteModelConnection: (id: string): Promise<void> =>
    request(`/config/model-connections/${encodeURIComponent(id)}`, { method: "DELETE" }),

  setDefaultModel: (id: string): Promise<{ defaultProfile: string }> =>
    request(`/config/model-profiles/${encodeURIComponent(id)}/default`, { method: "PUT" }),

  testModel: (id: string): Promise<ModelTestResult> =>
    request(`/config/model-profiles/${encodeURIComponent(id)}/test`, { method: "POST" }),

  ollamaStatus: (): Promise<OllamaStatus> => request("/config/models/ollama-status"),

  getVoice: (): Promise<VoiceSettings> => request("/config/voice"),

  /** 部分更新 [voice]（托盘静音等），返回更新后的 voice。 */
  putVoice: (body: Partial<VoiceSettings>): Promise<VoiceSettings> =>
    request("/config/voice", { method: "PUT", body: JSON.stringify(body) }),

  /** [character] 当前值（activeSkin）。 */
  getCharacter: (): Promise<CharacterSettings> => request("/config/character"),

  /** 更新 [character]（3.3 一键换肤），返回更新后的视图。 */
  setCharacter: (body: Partial<CharacterSettings>): Promise<CharacterSettings> =>
    request("/config/character", { method: "PUT", body: JSON.stringify(body) }),

  /** 人格当前配置 + 内置预设目录（6.13），一次拉齐供角色 tab 渲染。 */
  getPersona: (): Promise<PersonaFullView> => request("/config/persona"),

  /** 更新 [character.persona]（全量当前编辑态），返回更新后的 persona。 */
  putPersona: (body: PersonaSettings): Promise<PersonaSettings> =>
    request("/config/persona", { method: "PUT", body: JSON.stringify(body) }),
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
