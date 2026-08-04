/**
 * settings store —— 通用设置（界面语言）的前端镜像（M1-CTX）。
 *
 * 事实源在 sidecar config.toml：
 * - hydrate()：启动时从 GET /config 同步（sidecar 未就绪则保持默认，稍后重试）；
 * - setLanguage()：乐观更新即时生效，PUT 失败回滚，保证与事实源一致。
 */
import { create } from "zustand";
import { configApi } from "../api/configClient";
import { DEFAULT_LOCALE, type Language } from "../i18n/strings";

interface SettingsState {
  language: Language;
  /** 从 sidecar 拉取语言设置；返回是否成功（失败保持默认值，供调用方重试）。 */
  hydrate: () => Promise<boolean>;
  /** 切换语言：本地即时生效 + 持久化到 sidecar，失败回滚。 */
  setLanguage: (language: Language) => void;
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
    configApi.updateGeneral({ language }).catch(() => set({ language: previous }));
  },
}));
