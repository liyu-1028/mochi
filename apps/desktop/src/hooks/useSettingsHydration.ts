/**
 * useSettingsHydration —— 窗口启动时从 sidecar 同步语言/省电等通用设置 + 跨窗口跟随。
 *
 * 事实源在 sidecar config.toml（store/settings.ts hydrate）；
 * 角色窗口（App）与面板窗口（PanelShell）是各自独立的 JS 上下文，
 * zustand 不跨窗口共享，因此每个窗口启动时都要独立 hydrate。
 * sidecar 未就绪时重试数次后放弃（保持默认）。
 *
 * 另监听 mochi:language-changed / mochi:power-save-changed：任一窗口切换后，
 * 本窗口本地跟随（applyRemote* 只 set，不广播/持久化，无回环）。
 */
import { useEffect } from "react";
import { listen } from "@tauri-apps/api/event";
import type { Language } from "../i18n/strings";
import { EVENT_LANGUAGE_CHANGED, EVENT_POWER_SAVE_CHANGED } from "../panelWindow";
import { useSettings } from "../store/settings";

export function useSettingsHydration(): void {
  useEffect(() => {
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tryHydrate = async () => {
      attempts += 1;
      const ok = await useSettings.getState().hydrate();
      if (!ok && attempts < 5) {
        timer = setTimeout(tryHydrate, 1500);
      }
    };
    void tryHydrate();
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    const unlistenLang = listen<{ language: Language }>(EVENT_LANGUAGE_CHANGED, (e) => {
      useSettings.getState().applyRemoteLanguage(e.payload.language);
    });
    const unlistenPower = listen<{ powerSave: boolean }>(EVENT_POWER_SAVE_CHANGED, (e) => {
      useSettings.getState().applyRemotePowerSave(e.payload.powerSave);
    });
    return () => {
      unlistenLang.then((fn) => fn());
      unlistenPower.then((fn) => fn());
    };
  }, []);
}
