/**
 * i18n 入口（M1-CTX）：无库方案——字典 + 纯函数 translate + React hook。
 *
 * - 语言事实源在 sidecar config（store/settings.ts 同步），不用 localStorage；
 * - 回退链：当前语言 → zh-CN（源语言）→ 键本身（缺键不崩、可被发现）；
 * - 插值：`{name}` 占位符经 vars 替换。
 */
import { useCallback } from "react";
import { useSettings } from "../store/settings";
import { DEFAULT_LOCALE, STRINGS, type Language } from "./strings";

export type I18nVars = Record<string, string | number>;

/** 纯函数：按键取文案并插值；缺键回退 zh-CN → 键本身。 */
export function translate(locale: Language, key: string, vars?: I18nVars): string {
  let text = STRINGS[locale]?.[key] ?? STRINGS[DEFAULT_LOCALE][key] ?? key;
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      text = text.replaceAll(`{${name}}`, String(value));
    }
  }
  return text;
}

/** 组件用 hook：返回 t(key, vars?) 与当前 locale，语言切换即时重渲染。 */
export function useI18n() {
  const locale = useSettings((s) => s.language);
  const t = useCallback((key: string, vars?: I18nVars) => translate(locale, key, vars), [locale]);
  return { t, locale };
}

export type { Language };
