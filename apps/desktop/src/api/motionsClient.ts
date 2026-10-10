/** Imported VRMA library; category records role defaults versus user extensions. */
import { resolveHttpBaseUrl } from "./configClient";

export interface MotionEntry {
  id: string;
  label: string;
  kind: "oneshot" | "loop";
  durationMs: number;
  priority: number;
  cooldownMs: number;
  agentSelectable: boolean;
  tags: readonly string[];
  file: string;
  createdAt: string;
  /** 素材作者要求的署名；旧动作库可省略。 */
  credit?: string;
  category?: "builtin" | "custom";
  source?: "builtin" | "user";
  skinId?: string | null;
}

export type MotionPatch = Partial<
  Pick<
    MotionEntry,
    | "label"
    | "kind"
    | "priority"
    | "cooldownMs"
    | "agentSelectable"
    | "tags"
    | "category"
    | "credit"
  >
>;

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
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

export const MOTIONS_CHANGED = "mochi:motions-changed";
async function mutate<T>(path: string, init: RequestInit): Promise<T> {
  const result = await request<T>(path, init);
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(MOTIONS_CHANGED));
    if (typeof BroadcastChannel !== "undefined") {
      const channel = new BroadcastChannel(MOTIONS_CHANGED);
      channel.postMessage("changed");
      channel.close();
    }
  }
  return result;
}

export const motionsApi = {
  listMotions: (skinId?: string): Promise<MotionEntry[]> =>
    request(`/motions${skinId ? `?skinId=${encodeURIComponent(skinId)}` : ""}`),

  /** Import an unmodified VRMA file and its measured duration. */
  importMotion: (
    file: File,
    meta: {
      id: string;
      label: string;
      kind: "oneshot" | "loop";
      durationMs: number;
      priority: number;
      cooldownMs: number;
      agentSelectable: boolean;
      tags: readonly string[];
      category: "builtin" | "custom";
      credit: string;
    },
  ): Promise<MotionEntry> => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("id", meta.id);
    formData.append("label", meta.label);
    formData.append("kind", meta.kind);
    formData.append("durationMs", String(meta.durationMs));
    formData.append("priority", String(meta.priority));
    formData.append("cooldownMs", String(meta.cooldownMs));
    formData.append("agentSelectable", String(meta.agentSelectable));
    formData.append("tags", meta.tags.join(","));
    formData.append("category", meta.category);
    formData.append("credit", meta.credit);
    return mutate("/motions", { method: "POST", body: formData, headers: undefined });
  },

  updateMotion: (id: string, patch: MotionPatch): Promise<MotionEntry> =>
    mutate(`/motions/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(patch) }),

  deleteMotion: (id: string): Promise<void> =>
    mutate(`/motions/${encodeURIComponent(id)}`, { method: "DELETE" }),

  /** 动作文件资源 URL（three 加载器直取）。 */
  motionFileUrl: (entry: Pick<MotionEntry, "file">): string =>
    `${resolveHttpBaseUrl()}/motion-library/${entry.file}`,
};
