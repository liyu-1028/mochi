/**
 * skinsClient —— 皮肤系统 REST 封装（M1-S1，功能清单 3.x）。
 *
 * 皮肤是内容不是协议（persona 先例，ADR-0005 D1）：类型就地定义，
 * 不进 packages/protocol。列表的 resourceBaseUrl 为用户皮肤的 sidecar
 * 绝对 URL（内置静态皮肤已随静态类型下线移除，2026-09-28）。
 */
import { resolveHttpBaseUrl } from "./configClient";

export type ResourceTypeId = "live2d";
export type SkinSource = "builtin" | "user";

/** 语义动作实现绑定（skin.json v2，M-A；服务端只验结构，motionGroups 真实性加载时判）。 */
export interface Live2dActionBinding {
  motionGroups: readonly string[];
  expression?: string;
}

export type ActionKind = "oneshot" | "loop";
export type InterruptPolicy = "replace" | "queue" | "ignore";

/** 语义动作注册表条目（skin.json v2，M-A）。 */
export interface SkinAction {
  id: string;
  kind?: ActionKind;
  channels?: readonly string[];
  live2d?: Live2dActionBinding;
  /** 0~100，越高越优先（调度语义 M-B 生效） */
  priority?: number;
  interruptPolicy?: InterruptPolicy;
  cooldownMs?: number;
  /** 白名单铁律：仅 true 的动作可被 LLM 选择（协议规范 §11） */
  agentSelectable?: boolean;
  /** 降级链：同清单其他动作 id 或语义词表内动作 */
  fallback?: string;
}

/** skin.json 完整清单（渲染层按需取用，缺字段给默认）。 */
export interface SkinManifest {
  id: string;
  name: string;
  version: string;
  resourceType: ResourceTypeId;
  license: string;
  cubismVersion?: number;
  modelFile?: string;
  capabilities?: { motionGroups: readonly string[]; expressions: readonly string[] };
  actions?: readonly SkinAction[];
  credits?: Record<string, string>;
}

/** GET /skins 列表条目（展示 + 资源基址，前端不拼路径）。 */
export interface SkinSummary extends SkinManifest {
  source: SkinSource;
  resourceBaseUrl: string;
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

export const skinsApi = {
  listSkins: (): Promise<SkinSummary[]> => request("/skins"),

  /** 导入皮肤（zip 皮肤包）；不设 Content-Type 由浏览器定 boundary。 */
  importSkin: (file: File): Promise<SkinSummary> => {
    const formData = new FormData();
    formData.append("file", file);
    return request("/skins/import", { method: "POST", body: formData, headers: undefined });
  },

  deleteSkin: (id: string): Promise<void> =>
    request(`/skins/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
