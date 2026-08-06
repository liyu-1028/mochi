/**
 * SettingsModelSection —— 设置「模型」tab 内容（tab 化重构自 SettingsPanel）。
 *
 * provider 列表 / 新增 / 编辑 / 连通性测试 / 设为默认 / 删除 / 试用模式。
 * 切换默认模型、修改 provider 信息均即热生效（sidecar registry 按回合解析），无需重启。
 * 反馈条由本 section 自持（tab 化后各分区管理自己的 feedback）。
 */
import { useCallback, useEffect, useState } from "react";
import { emit } from "@tauri-apps/api/event";
import {
  TRIAL_PROVIDER_ID,
  configApi,
  type ProviderCreateInput,
  type ProviderSummary,
  type ProviderUpdateInput,
} from "../api/configClient";
import { useI18n } from "../i18n";
import { EVENT_PROVIDERS_CHANGED } from "../panelWindow";
import { ProviderForm } from "./ProviderForm";

export function SettingsModelSection() {
  const { t } = useI18n();
  const [providers, setProviders] = useState<ProviderSummary[]>([]);
  const [defaultId, setDefaultId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  /** 非 null 时表示表单处于编辑模式（修改已有 provider）。 */
  const [editing, setEditing] = useState<ProviderSummary | null>(null);
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

  async function handleSubmit(input: ProviderCreateInput) {
    if (editing) {
      // 编辑模式：只提交可变字段（id/kind 锁定；apiKey 留空 = 保留原 Key）
      const update: ProviderUpdateInput = {
        displayName: input.displayName,
        baseUrl: input.baseUrl,
        model: input.model,
        apiKey: input.apiKey,
      };
      await configApi.updateProvider(editing.id, update);
      setFeedback(t("settings.updatedFeedback", { name: input.displayName }));
    } else {
      await configApi.createProvider(input);
      setFeedback(t("settings.addedFeedback", { name: input.displayName }));
      // provider 列表变化 → 主窗口重新探测设置状态（清除待设置提示）
      void emit(EVENT_PROVIDERS_CHANGED);
    }
    setShowForm(false);
    setEditing(null);
    await refresh();
  }

  function closeForm() {
    setShowForm(false);
    setEditing(null);
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
    <>
      {feedback ? <p className="settings__feedback">{feedback}</p> : null}

      <ul className="settings__list">
        <li className="settings__item">
          <div className="settings__item-main">
            <strong>{t("settings.trialMode")}</strong>
            <span className="settings__item-sub">{t("settings.trialDesc")}</span>
          </div>
          {defaultId === TRIAL_PROVIDER_ID ? (
            <span className="settings__tag">{t("settings.inUse")}</span>
          ) : (
            <button className="btn btn--ghost" onClick={() => handleSetDefault(TRIAL_PROVIDER_ID)}>
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
                disabled={showForm || busyId === p.id}
                onClick={() => {
                  setEditing(p);
                  setShowForm(true);
                  setFeedback(null);
                }}
              >
                {t("common.edit")}
              </button>
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
        <ProviderForm
          key={editing?.id ?? "__create__"}
          initial={editing ?? undefined}
          onSubmit={handleSubmit}
          onCancel={closeForm}
        />
      ) : (
        <button
          className="btn"
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
