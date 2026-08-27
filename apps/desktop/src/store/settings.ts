/**
 * settings store —— 通用设置（界面语言、省电模式）的前端镜像（M1-CTX；2.6）。
 *
 * 事实源在 sidecar config.toml：
 * - hydrate()：启动时从 GET /config 同步（sidecar 未就绪则保持默认，稍后重试）；
 * - setLanguage()/setPowerSave()：乐观更新即时生效，PUT 失败回滚，保证与事实源一致。
 *
 * 跨窗口：zustand 每窗口独立上下文，语言/省电变更各自广播
 * （mochi:language-changed / mochi:power-save-changed），其余窗口经
 * applyRemote* 本地跟随（不再二次广播/持久化，避免回环）。
 */
import { emit } from "@tauri-apps/api/event";
import { create } from "zustand";
import { configApi } from "../api/configClient";
import { DEFAULT_LOCALE, type Language } from "../i18n/strings";
import { EVENT_LANGUAGE_CHANGED, EVENT_POWER_SAVE_CHANGED } from "../panelWindow";

interface SettingsState {
  language: Language;
  /** 省电模式（2.6）：角色渲染钉 15fps + 暂停装饰动画。 */
  powerSave: boolean;
  /** 从 sidecar 拉取设置；返回是否成功（失败保持默认值，供调用方重试）。 */
  hydrate: () => Promise<boolean>;
  /** 切换语言：本地即时生效 + 持久化到 sidecar + 广播其余窗口，失败回滚。 */
  setLanguage: (language: Language) => void;
  /** 切换省电模式（同上链路）。 */
  setPowerSave: (powerSave: boolean) => void;
  /** 仅本地应用语言（跨窗口同步入口）：不广播、不持久化，防回环。 */
  applyRemoteLanguage: (language: Language) => void;
  /** 仅本地应用省电模式（跨窗口同步入口）。 */
  applyRemotePowerSave: (powerSave: boolean) => void;
}

/** 广播设置变更到其余窗口；非窗口环境（Node 测试）/ 无 Tauri runtime 降级为 no-op。 */
function broadcastSettings(
  event: string,
  payload: { language?: Language; powerSave?: boolean },
): void {
  if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) return;
  emit(event, payload).catch(() => {
    /* 广播失败不影响本窗口体验 */
  });
}

export const useSettings = create<SettingsState>()((set, get) => ({
  language: DEFAULT_LOCALE,
  powerSave: false,

  hydrate: async () => {
    try {
      const config = await configApi.getConfig();
      const language = config.general?.language;
      if (language === "zh-CN" || language === "en") {
        set({ language });
      }
      if (typeof config.general?.powerSave === "boolean") {
        set({ powerSave: config.general.powerSave });
      }
      return true;
    } catch {
      // sidecar 未就绪：保持默认，供调用方重试
      return false;
    }
  },

  setLanguage: (language) => {
    const previous = get().language;
    if (language === previous) return;
    set({ language });
    broadcastSettings(EVENT_LANGUAGE_CHANGED, { language });
    configApi.updateGeneral({ language }).catch(() => {
      set({ language: previous });
      broadcastSettings(EVENT_LANGUAGE_CHANGED, { language: previous });
    });
  },

  setPowerSave: (powerSave) => {
    const previous = get().powerSave;
    if (powerSave === previous) return;
    set({ powerSave });
    broadcastSettings(EVENT_POWER_SAVE_CHANGED, { powerSave });
    configApi.updateGeneral({ powerSave }).catch(() => {
      set({ powerSave: previous });
      broadcastSettings(EVENT_POWER_SAVE_CHANGED, { powerSave: previous });
    });
  },

  applyRemoteLanguage: (language) => {
    if ((language === "zh-CN" || language === "en") && get().language !== language) {
      set({ language });
    }
  },

  applyRemotePowerSave: (powerSave) => {
    if (typeof powerSave === "boolean" && get().powerSave !== powerSave) {
      set({ powerSave });
    }
  },
}));
