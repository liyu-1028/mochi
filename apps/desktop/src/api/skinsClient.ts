/**
 * skinsClient —— 皮肤系统 REST 封装（M1-S1，功能清单 3.x）。
 *
 * 皮肤是内容不是协议（persona 先例，ADR-0005 D1）：类型就地定义，
 * 不进 packages/protocol。列表的 resourceBaseUrl 双轨：
 * 内置走 webview 相对路径 /skins/<id>，用户皮肤走 sidecar 绝对 URL。
 */
import { resolveHttpBaseUrl } from "./configClient";

export type ResourceTypeId = "live2d" | "static";
export type SkinSource = "builtin" | "user";

/** 静态皮肤单状态动画开关（skin.json v1）。 */
export interface AnimationParams {
  float: boolean;
  breathe: boolean;
  sway: boolean;
}

/** 静态皮肤情绪表达（最小可用：微缩放）。 */
export interface EmotionEffect {
  scale: number;
  tint: string | null;
}

/** skin.json v1 完整清单（渲染层按需取用，缺字段给默认）。 */
export interface SkinManifest {
  id: string;
  name: string;
  version: string;
  resourceType: ResourceTypeId;
  license: string;
  cubismVersion?: number;
  modelFile?: string;
  imageFile?: string;
  capabilities?: { motionGroups: readonly string[]; expressions: readonly string[] };
  animation?: Partial<Record<string, Partial<AnimationParams>>>;
  emotionMapping?: Record<string, EmotionEffect>;
  credits?: Record<string, string>;
}

/** GET /skins 列表条目（展示 + 资源基址，前端不拼路径）。 */
export interface SkinSummary extends SkinManifest {
  source: SkinSource;
  resourceBaseUrl: string;
}

/** 历史配置占位 "default" 解析为默认内置皮肤（服务端 resolve_skin_id 同构）。 */
export const DEFAULT_BUILTIN_SKIN_ID = "hiyori";

export function resolveSkinId(skinId: string): string {
  return skinId === "default" ? DEFAULT_BUILTIN_SKIN_ID : skinId;
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

  /** 导入皮肤（PNG / zip，magic 分流）；不设 Content-Type 由浏览器定 boundary。 */
  importSkin: (file: File, skinName?: string): Promise<SkinSummary> => {
    const formData = new FormData();
    formData.append("file", file);
    if (skinName) formData.append("skin_name", skinName);
    return request("/skins/import", { method: "POST", body: formData, headers: undefined });
  },

  deleteSkin: (id: string): Promise<void> =>
    request(`/skins/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
