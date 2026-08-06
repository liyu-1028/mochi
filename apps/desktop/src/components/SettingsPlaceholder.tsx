/**
 * SettingsPlaceholder —— 尚未实装 tab 的占位（语音 / 隐私）。
 *
 * 功能清单 7.1 设置中心分组先行呈现，实装后替换为对应 section。
 */
import { useI18n } from "../i18n";

export function SettingsPlaceholder() {
  const { t } = useI18n();
  return <p className="settings__item-sub settings__placeholder">{t("settings.comingSoon")}</p>;
}
