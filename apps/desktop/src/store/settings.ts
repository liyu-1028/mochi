/**
 * settings store —— 通用设置（界面语言）的前端镜像（M1-CTX）。
 *
 * 事实源在 sidecar config.toml：
 * - hydrate()：启动时从 GET /config 同步（sidecar 未就绪则保持默认，稍后重试）；
 * - setLanguage()：乐观更新即时生效，PUT 失败回滚，保证与事实源一致。
 *
 * 跨窗口：zustand 每窗口独立上下文，setLanguage 会广播 mochi:language-changed，
 * 其余窗口经 applyRemoteLanguage 本地跟随（不再二次广播/持久化，避免回环）。
 */
import { emit } from "@tauri-apps/api/event";
import { create } from "zustand";
import { configApi } from "../api/configClient";
import { DEFAULT_LOCALE, type Language } from "../i18n/strings";
import { EVENT_LANGUAGE_CHANGED } from "../panelWindow";

interface SettingsState {
  language: Language;
  /** 从 sidecar 拉取语言设置；返回是否成功（失败保持默认值，供调用方重试）。 */
  hydrate: () => Promise<boolean>;
  /** 切换语言：本地即时生效 + 持久化到 sidecar + 广播其余窗口，失败回滚。 */
  setLanguage: (language: Language) => void;
  /** 仅本地应用语言（跨窗口同步入口）：不广播、不持久化，防回环。 */
  applyRemoteLanguage: (language: Language) => void;
}

/** 广播语言变更到其余窗口；非窗口环境（Node 测试）/ 无 Tauri runtime 降级为 no-op。 */
function broadcastLanguage(language: Language): void {
  if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) return;
  emit(EVENT_LANGUAGE_CHANGED, { language }).catch(() => {
    /* 广播失败不影响本窗口体验 */
  });
}

export const useSettings = create<SettingsState>()((set, get) => ({
  language: DEFAULT_LOCALE,

  hydrate: async () => {
    try {
      const config = await configApi.getConfig();
      const language = config.general?.language;
      if (language === "zh-CN" || language === "en") {
        set({ language });
      }
      return true;
    } catch {
      // sidecar 未就绪：保持默认语言，供调用方重试
      return false;
    }
  },

  setLanguage: (language) => {
    const previous = get().language;
    if (language === previous) return;
    set({ language });
    broadcastLanguage(language);
    configApi.updateGeneral({ language }).catch(() => {
      set({ language: previous });
      broadcastLanguage(previous);
    });
  },

  applyRemoteLanguage: (language) => {
    if ((language === "zh-CN" || language === "en") && get().language !== language) {
      set({ language });
    }
  },
}));
