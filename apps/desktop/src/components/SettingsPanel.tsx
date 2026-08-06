/**
 * SettingsPanel —— 设置模态面板（tab 化重构）。
 *
 * 布局：左侧 tab 导航 + 右侧内容区（功能清单 7.1 五分组：
 * 通用 / 模型 / 角色 / 语音 / 隐私）。tab 为本地状态，切换不跨窗口。
 *
 * 分组：
 * - 通用（SettingsGeneralSection）：界面语言；
 * - 模型（SettingsModelSection）：provider 管理（列表/新增/编辑/测试/默认/删除）；
 * - 角色 / 语音 / 隐私（SettingsPlaceholder）：占位，人格选择随后接入（6.13）。
 *
 * 切换默认模型、修改 provider 均即热生效（sidecar registry 按回合解析）。
 */
import { useState } from "react";
import { useI18n } from "../i18n";
import { SettingsGeneralSection } from "./SettingsGeneralSection";
import { SettingsModelSection } from "./SettingsModelSection";
import { SettingsPlaceholder } from "./SettingsPlaceholder";

interface SettingsPanelProps {
  onClose: () => void;
}

/** 设置 tab 标识（7.1 五分组，顺序即呈现顺序）。 */
export type SettingsTabId = "general" | "model" | "character" | "voice" | "privacy";

const TABS: ReadonlyArray<{ id: SettingsTabId; labelKey: string }> = [
  { id: "general", labelKey: "settings.sectionGeneral" },
  { id: "model", labelKey: "settings.sectionModel" },
  { id: "character", labelKey: "settings.sectionCharacter" },
  { id: "voice", labelKey: "settings.sectionVoice" },
  { id: "privacy", labelKey: "settings.sectionPrivacy" },
];

export function SettingsPanel({ onClose }: SettingsPanelProps) {
  const { t } = useI18n();
  const [tab, setTab] = useState<SettingsTabId>("general");

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div
        className="settings settings--tabbed"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={t("settings.title")}
      >
        {/* data-tauri-drag-region：无边框面板窗口以头部为拖拽区（button 子元素自动豁免） */}
        <header className="settings__header" data-tauri-drag-region>
          <h2>{t("settings.title")}</h2>
          <button className="settings__close" onClick={onClose} aria-label={t("common.close")}>
            ×
          </button>
        </header>

        <div className="settings__body">
          <nav className="settings__nav" aria-label={t("settings.title")}>
            {TABS.map(({ id, labelKey }) => (
              <button
                key={id}
                type="button"
                className={`settings__nav-item${tab === id ? " settings__nav-item--active" : ""}`}
                aria-current={tab === id ? "page" : undefined}
                onClick={() => setTab(id)}
              >
                {t(labelKey)}
              </button>
            ))}
          </nav>

          <div className="settings__content">
            {tab === "general" ? <SettingsGeneralSection /> : null}
            {tab === "model" ? <SettingsModelSection /> : null}
            {tab === "character" ? <SettingsPlaceholder /> : null}
            {tab === "voice" ? <SettingsPlaceholder /> : null}
            {tab === "privacy" ? <SettingsPlaceholder /> : null}
          </div>
        </div>
      </div>
    </div>
  );
}
