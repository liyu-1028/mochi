/**
 * memoryClient —— 记忆管理 REST 封装（M1-S3，功能清单 6.4）。
 *
 * 记忆是内容不是协议：类型就地定义，与 skinsClient 同模式。
 * CRUD 端点走 sidecar REST，与 sessionApi/configApi 共用 request 基础设施。
 */
import { resolveHttpBaseUrl } from "./configClient";

export type MemoryCategory = "fact" | "preference";
export type MemorySource = "auto" | "manual";

/** 单条记忆（与服务端 MemoryItem 同构，camelCase）。 */
export interface MemoryItem {
  id: string;
  category: MemoryCategory;
  content: string;
  source: MemorySource;
  createdAt: number;
  updatedAt: number;
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
      // 非 JSON 错误体
    }
    throw new Error(typeof detail === "string" ? detail : "请求失败");
  }
  if (resp.status === 204) {
    return undefined as T;
  }
  return resp.json() as Promise<T>;
}

export const memoryApi = {
  listMemories: (category?: MemoryCategory): Promise<MemoryItem[]> =>
    request(`/memories${category ? `?category=${category}` : ""}`),

  createMemory: (content: string, category: MemoryCategory = "fact"): Promise<MemoryItem> =>
    request("/memories", { method: "POST", body: JSON.stringify({ content, category }) }),

  updateMemory: (id: string, content: string): Promise<MemoryItem> =>
    request(`/memories/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),

  deleteMemory: (id: string): Promise<void> =>
    request(`/memories/${encodeURIComponent(id)}`, { method: "DELETE" }),

  clearAll: (): Promise<void> => request("/memories", { method: "DELETE" }),
};
