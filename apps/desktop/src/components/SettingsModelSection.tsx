/** 模型设置：展示具体模型配置；厂商账号/Key 作为共享连接由表单自动管理。 */
import { useCallback, useEffect, useState } from "react";
import { emit } from "@tauri-apps/api/event";
import {
  TRIAL_PROFILE_ID,
  configApi,
  type ModelProfileSummary,
  type ProviderPreset,
} from "../api/configClient";
import { useI18n } from "../i18n";
import { EVENT_PROVIDERS_CHANGED } from "../panelWindow";
import { ProviderForm } from "./ProviderForm";

export function SettingsModelSection() {
  const { t } = useI18n();
  const [profiles, setProfiles] = useState<ModelProfileSummary[]>([]);
  const [presets, setPresets] = useState<ProviderPreset[]>([]);
  const [defaultId, setDefaultId] = useState<string>(TRIAL_PROFILE_ID);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<ModelProfileSummary | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [nextProfiles, nextPresets] = await Promise.all([
        configApi.listModelProfiles(),
        configApi.listModelPresets(),
      ]);
      setProfiles(nextProfiles);
      setPresets(nextPresets);
      setDefaultId(nextProfiles.find((profile) => profile.isDefault)?.id ?? TRIAL_PROFILE_ID);
    } catch {
      setFeedback(t("settings.feedbackUnreachable"));
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function closeForm() {
    setShowForm(false);
    setEditing(null);
  }

  async function handleSaved(profile: ModelProfileSummary) {
    setFeedback(
      t(editing ? "settings.updatedFeedback" : "settings.addedFeedback", {
        name: profile.displayName,
      }),
    );
    closeForm();
    void emit(EVENT_PROVIDERS_CHANGED);
    await refresh();
  }

  async function handleTest(id: string) {
    setBusyId(id);
    setFeedback(null);
    try {
      const result = await configApi.testModel(id);
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
    await configApi.setDefaultModel(id);
    setFeedback(t("settings.switchedFeedback", { id }));
    await refresh();
  }

  async function handleDelete(profile: ModelProfileSummary) {
    const shared = profiles.filter((item) => item.connectionId === profile.connectionId);
    if (shared.length === 1) {
      await configApi.deleteModelConnection(profile.connectionId);
    } else {
      await configApi.deleteModelProfile(profile.id);
    }
    setFeedback(t("settings.deletedFeedback", { id: profile.displayName }));
    void emit(EVENT_PROVIDERS_CHANGED);
    await refresh();
  }

  return (
    <>
      <p className="settings__hint">{t("settings.modelSetupHint")}</p>
      {feedback ? <p className="settings__feedback">{feedback}</p> : null}

      <ul className="settings__list">
        <li className="settings__item">
          <div className="settings__item-main">
            <strong>{t("settings.trialMode")}</strong>
            <span className="settings__item-sub">{t("settings.trialDesc")}</span>
          </div>
          {defaultId === TRIAL_PROFILE_ID ? (
            <span className="settings__tag">{t("settings.inUse")}</span>
          ) : (
            <button
              className="btn btn--ghost"
              onClick={() => void handleSetDefault(TRIAL_PROFILE_ID)}
            >
              {t("settings.setDefault")}
            </button>
          )}
        </li>

        {profiles.map((profile) => {
          const preset = presets.find((item) => item.id === profile.presetId);
          return (
            <li key={profile.id} className="settings__item">
              <div className="settings__item-main">
                <strong>{profile.displayName}</strong>
                <span className="settings__item-sub">
                  {preset?.displayName ?? profile.presetId} · {profile.model}
                  {profile.maskedKey ? ` · Key ${profile.maskedKey}` : ""}
                </span>
                <span className="settings__item-sub">
                  {t(`providerForm.protocol.${profile.protocol}`)} · {profile.connectionName}
                </span>
              </div>
              <div className="settings__item-actions">
                <button
                  className="btn btn--ghost"
                  disabled={showForm || busyId === profile.id}
                  onClick={() => {
                    setEditing(profile);
                    setShowForm(true);
                    setFeedback(null);
                  }}
                >
                  {t("common.edit")}
                </button>
                <button
                  className="btn btn--ghost"
                  disabled={busyId === profile.id}
                  onClick={() => void handleTest(profile.id)}
                >
                  {busyId === profile.id ? t("settings.testing") : t("settings.test")}
                </button>
                {profile.isDefault ? (
                  <span className="settings__tag">{t("settings.inUse")}</span>
                ) : (
                  <button
                    className="btn btn--ghost"
                    onClick={() => void handleSetDefault(profile.id)}
                  >
                    {t("settings.setDefault")}
                  </button>
                )}
                <button
                  className="btn btn--ghost settings__danger"
                  onClick={() => void handleDelete(profile)}
                >
                  {t("common.delete")}
                </button>
              </div>
            </li>
          );
        })}
      </ul>

      {showForm ? (
        <ProviderForm
          key={editing?.id ?? "__create__"}
          presets={presets}
          profiles={profiles}
          initial={editing ?? undefined}
          onSaved={handleSaved}
          onCancel={closeForm}
        />
      ) : (
        <button
          className="btn"
          disabled={presets.length === 0}
          onClick={() => {
            setEditing(null);
            setShowForm(true);
            setFeedback(null);
          }}
        >
          {t("settings.addProvider")}
        </button>
      )}
    </>
  );
}
