/**
 * SettingsGeneralSection —— 设置「通用」tab 内容（tab 化重构自 SettingsPanel）。
 *
 * 界面语言：事实源在 sidecar config，切换即生效并持久化 + 跨窗口广播。
 * 省电模式（2.6）：角色渲染钉 15fps + 暂停装饰动画；同样持久化 + 跨窗口广播。
 * 诊断包导出（1.8）与设置导入导出（7.1）：日志脱敏打包 zip / 设置 JSON 往返。
 */
import { useState } from "react";
import { useI18n } from "../i18n";
import type { Language } from "../i18n/strings";
import { useSettings } from "../store/settings";
import { exportDiagnostics, exportSettings, importSettings } from "../api/diagnosticsClient";

export function SettingsGeneralSection() {
  const { t } = useI18n();
  const language = useSettings((s) => s.language);
  const setLanguage = useSettings((s) => s.setLanguage);
  const powerSave = useSettings((s) => s.powerSave);
  const setPowerSave = useSettings((s) => s.setPowerSave);
  const hydrate = useSettings((s) => s.hydrate);
  const [feedback, setFeedback] = useState<string | null>(null);

  const run = async (label: string, action: () => Promise<unknown>) => {
    try {
      const result = await action();
      setFeedback(result === null ? null : t(label));
    } catch {
      setFeedback(t("settings.ioFailed"));
    }
  };

  return (
    <>
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
      <label className="settings__field settings__field--toggle">
        <span>{t("settings.powerSave")}</span>
        <input
          type="checkbox"
          checked={powerSave}
          onChange={(e) => setPowerSave(e.target.checked)}
          aria-label={t("settings.powerSave")}
        />
        <small className="settings__hint">{t("settings.powerSaveHint")}</small>
      </label>
      <div className="settings__field settings__field--actions">
        <button type="button" onClick={() => void run("settings.diagDone", exportDiagnostics)}>
          {t("settings.exportDiagnostics")}
        </button>
        <button type="button" onClick={() => void run("settings.exportDone", exportSettings)}>
          {t("settings.exportSettings")}
        </button>
        <button
          type="button"
          onClick={() =>
            void run("settings.importDone", async () => {
              await importSettings();
              await hydrate(); // 应用后同步本窗口镜像
            })
          }
        >
          {t("settings.importSettings")}
        </button>
        {feedback !== null ? <small className="settings__hint">{feedback}</small> : null}
      </div>
    </>
  );
}
