/**
 * SettingsGeneralSection —— 设置「通用」tab 内容（tab 化重构自 SettingsPanel）。
 *
 * 界面语言：事实源在 sidecar config，切换即生效并持久化 + 跨窗口广播。
 */
import { useI18n } from "../i18n";
import type { Language } from "../i18n/strings";
import { useSettings } from "../store/settings";

export function SettingsGeneralSection() {
  const { t } = useI18n();
  const language = useSettings((s) => s.language);
  const setLanguage = useSettings((s) => s.setLanguage);

  return (
    <label className="settings__field">
      <span>{t("settings.language")}</span>
      <select
        value={language}
        onChange={(e) => setLanguage(e.target.value as Language)}
        aria-label={t("settings.language")}
      >
        <option value="zh-CN">{t("settings.languageZh")}</option>
        <option value="en">{t("settings.languageEn")}</option>
      </select>
    </label>
  );
}
