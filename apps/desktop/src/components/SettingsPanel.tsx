/**
 * SettingsPanel —— 设置模态面板（M0-S2 模型管理 + M1-CTX 通用分组）。
 *
 * 分组：
 * - 通用：界面语言（事实源在 sidecar config，切换即生效并持久化）；
 * - 模型：provider 列表 / 新增 / 连通性测试 / 设为默认 / 删除 / 试用模式。
 * 切换默认模型即热生效（sidecar registry 按回合解析），无需重启。
 */
import { useCallback, useEffect, useState } from "react";
import { emit } from "@tauri-apps/api/event";
import {
  TRIAL_PROVIDER_ID,
  configApi,
  type ProviderCreateInput,
  type ProviderSummary,
} from "../api/configClient";
import { useI18n } from "../i18n";
import { EVENT_PROVIDERS_CHANGED } from "../panelWindow";
import { useSettings } from "../store/settings";
import type { Language } from "../i18n/strings";
import { ProviderForm } from "./ProviderForm";

interface SettingsPanelProps {
  onClose: () => void;
}

export function SettingsPanel({ onClose }: SettingsPanelProps) {
  const { t } = useI18n();
  const language = useSettings((s) => s.language);
  const setLanguage = useSettings((s) => s.setLanguage);
  const [providers, setProviders] = useState<ProviderSummary[]>([]);
  const [defaultId, setDefaultId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const kindLabel: Record<string, string> = {
    ollama: t("settings.kindOllama"),
    openai_compatible: t("settings.kindOpenAiCompat"),
    anthropic: t("settings.kindAnthropic"),
  };

  const refresh = useCallback(async () => {
    try {
      const list = await configApi.listProviders();
      setProviders(list);
      setDefaultId(list.find((p) => p.isDefault)?.id ?? null);
    } catch {
      setFeedback(t("settings.feedbackUnreachable"));
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleCreate(input: ProviderCreateInput) {
    await configApi.createProvider(input);
    setShowForm(false);
    setFeedback(t("settings.addedFeedback", { name: input.displayName }));
    // provider 列表变化 → 主窗口重新探测设置状态（清除待设置提示）
    void emit(EVENT_PROVIDERS_CHANGED);
    await refresh();
  }

  async function handleTest(id: string) {
    setBusyId(id);
    setFeedback(null);
    try {
      const result = await configApi.testProvider(id);
      setFeedback(
        result.ok
          ? t("settings.testOk", { id })
          : t("settings.testFail", { id, hint: result.hint ?? t("settings.unknownReason") }),
      );
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : t("settings.testError"));
    } finally {
      setBusyId(null);
    }
  }

  async function handleSetDefault(id: string) {
    await configApi.setDefault(id);
    setFeedback(t("settings.switchedFeedback", { id }));
    await refresh();
  }

  async function handleDelete(id: string) {
    await configApi.deleteProvider(id);
    setFeedback(t("settings.deletedFeedback", { id }));
    // provider 列表变化（可能删空）→ 主窗口重新探测，必要时回到待设置提示
    void emit(EVENT_PROVIDERS_CHANGED);
    await refresh();
  }

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings" onClick={(e) => e.stopPropagation()}>
        {/* data-tauri-drag-region：无边框面板窗口以头部为拖拽区（button 子元素自动豁免） */}
        <header className="settings__header" data-tauri-drag-region>
          <h2>{t("settings.title")}</h2>
          <button className="settings__close" onClick={onClose} aria-label={t("common.close")}>
            ×
          </button>
        </header>

        {feedback ? <p className="settings__feedback">{feedback}</p> : null}

        {/* 通用分组 */}
        <h3 className="settings__section">{t("settings.sectionGeneral")}</h3>
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

        {/* 模型分组 */}
        <h3 className="settings__section">{t("settings.sectionModel")}</h3>
        <ul className="settings__list">
          <li className="settings__item">
            <div className="settings__item-main">
              <strong>{t("settings.trialMode")}</strong>
              <span className="settings__item-sub">{t("settings.trialDesc")}</span>
            </div>
            {defaultId === TRIAL_PROVIDER_ID ? (
              <span className="settings__tag">{t("settings.inUse")}</span>
            ) : (
              <button
                className="btn btn--ghost"
                onClick={() => handleSetDefault(TRIAL_PROVIDER_ID)}
              >
                {t("settings.setDefault")}
              </button>
            )}
          </li>
          {providers.map((p) => (
            <li key={p.id} className="settings__item">
              <div className="settings__item-main">
                <strong>{p.displayName}</strong>
                <span className="settings__item-sub">
                  {kindLabel[p.kind] ?? p.kind} · {p.model}
                  {p.maskedKey ? ` · Key ${p.maskedKey}` : ""}
                </span>
              </div>
              <div className="settings__item-actions">
                <button
                  className="btn btn--ghost"
                  disabled={busyId === p.id}
                  onClick={() => handleTest(p.id)}
                >
                  {busyId === p.id ? t("settings.testing") : t("settings.test")}
                </button>
                {p.isDefault ? (
                  <span className="settings__tag">{t("settings.inUse")}</span>
                ) : (
                  <button className="btn btn--ghost" onClick={() => handleSetDefault(p.id)}>
                    {t("settings.setDefault")}
                  </button>
                )}
                <button
                  className="btn btn--ghost settings__danger"
                  onClick={() => handleDelete(p.id)}
                >
                  {t("common.delete")}
                </button>
              </div>
            </li>
          ))}
        </ul>

        {showForm ? (
          <ProviderForm onSubmit={handleCreate} onCancel={() => setShowForm(false)} />
        ) : (
          <button className="btn" onClick={() => setShowForm(true)}>
            {t("settings.addProvider")}
          </button>
        )}
      </div>
    </div>
  );
}
