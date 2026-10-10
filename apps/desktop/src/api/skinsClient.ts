/**
 * skinsClient —— 皮肤系统 REST 封装（M1-S1，功能清单 3.x）。
 *
 * 角色是内容不是协议（persona 先例，ADR-0005 D1）：类型就地定义，
 * 不进 packages/protocol。列表的 resourceBaseUrl 为用户皮肤的 sidecar
 * 绝对 URL（内置静态皮肤已随静态类型下线移除，2026-09-28）。
 */
import { resolveHttpBaseUrl } from "./configClient";

export type ResourceTypeId = "live2d" | "vrm";
export type SkinSource = "builtin" | "user";

/** 包络关键帧点：[t(ms), value]（skin.json v3，G3）。 */
export type ParamEnvelopePoint = readonly [number, number];

/** 单参数关键帧。 */
export interface ParamEnvelopeKeyframe {
  param: string;
  points: readonly ParamEnvelopePoint[];
}

/** 声明式参数包络（skin.json v3，G3）：皮肤作者免 Editor 自定义动作。 */
export interface ParamEnvelopeBinding {
  durationMs: number;
  easing?: "linear" | "smoothstep";
  keyframes: readonly ParamEnvelopeKeyframe[];
}

/** 语义动作实现绑定（skin.json v2，M-A；v3 增 paramEnvelope）。 */
export interface Live2dActionBinding {
  /** 与服务端一致：缺省 = 空列表（包络-only 绑定合法） */
  motionGroups?: readonly string[];
  expression?: string;
  /** v3：声明式参数包络；声明后任何 Cubism 模型可演（缺参数运行时静默跳过）。 */
  paramEnvelope?: ParamEnvelopeBinding;
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
  /** 动作时长 ms（v3，G3）：占位窗口；缺省用前端默认值 */
  durationMs?: number;
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

  /** 导入 .vrm 角色文件或 zip 皮肤包；不设 Content-Type 由浏览器定 boundary。 */
  importSkin: (file: File): Promise<SkinSummary> => {
    const formData = new FormData();
    formData.append("file", file);
    return request("/skins/import", { method: "POST", body: formData, headers: undefined });
  },

  /** 导入动作扩展包（G4）：给已导入的皮肤追加动作；不设 Content-Type 由浏览器定 boundary。 */
  importMotionPack: (file: File): Promise<SkinSummary> => {
    const formData = new FormData();
    formData.append("file", file);
    return request("/skins/import-motion-pack", {
      method: "POST",
      body: formData,
      headers: undefined,
    });
  },

  deleteSkin: (id: string): Promise<void> =>
    request(`/skins/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
