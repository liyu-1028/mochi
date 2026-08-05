/**
 * ProviderForm —— 模型提供方的新增/编辑表单（纯受控组件，无表单库）。
 *
 * - 无 initial：新增模式，提交完整 ProviderCreateInput；
 * - 有 initial：编辑模式，回填现有值；id 与类型锁定
 *   （后端 PUT 不支持改 kind/id，换类型请删除后重建）；
 *   API Key 留空 = 保留原 Key 不变。
 */
import { useState, type FormEvent } from "react";
import type { ProviderCreateInput, ProviderKind, ProviderSummary } from "../api/configClient";
import { useI18n } from "../i18n";

interface ProviderFormProps {
  /** 传入已有 provider 时进入编辑模式。 */
  initial?: ProviderSummary;
  onSubmit: (input: ProviderCreateInput) => Promise<void>;
  onCancel: () => void;
}

const ID_PATTERN = /^[a-z0-9][a-z0-9_-]*$/;

export function ProviderForm({ initial, onSubmit, onCancel }: ProviderFormProps) {
  const { t } = useI18n();
  const isEdit = initial !== undefined;
  const [kind, setKind] = useState<ProviderKind>(initial?.kind ?? "openai_compatible");
  const [id, setId] = useState(initial?.id ?? "");
  const [displayName, setDisplayName] = useState(initial?.displayName ?? "");
  const [baseUrl, setBaseUrl] = useState(initial?.baseUrl ?? "");
  const [model, setModel] = useState(initial?.model ?? "");
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isOllama = kind === "ollama";

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (!isEdit && !ID_PATTERN.test(id)) {
      setError(t("providerForm.errId"));
      return;
    }
    if (!model.trim()) {
      setError(t("providerForm.errModel"));
      return;
    }

    setBusy(true);
    try {
      await onSubmit({
        id: id.trim(),
        kind,
        displayName: displayName.trim() || id.trim(),
        baseUrl: baseUrl.trim() || undefined,
        model: model.trim(),
        apiKey: isOllama ? undefined : apiKey.trim() || undefined,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : t("providerForm.errSave"));
      setBusy(false);
    }
  }

  return (
    <form className="settings__form" onSubmit={handleSubmit}>
      <label className="settings__field">
        <span>{t("providerForm.kind")}</span>
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as ProviderKind)}
          disabled={isEdit}
        >
          <option value="openai_compatible">{t("providerForm.kindOpenAi")}</option>
          <option value="ollama">{t("providerForm.kindOllama")}</option>
          <option value="anthropic">{t("providerForm.kindAnthropic")}</option>
        </select>
      </label>
      <label className="settings__field">
        <span>{t("providerForm.id")}</span>
        <input
          value={id}
          onChange={(e) => setId(e.target.value)}
          placeholder={t("providerForm.idPlaceholder")}
          disabled={isEdit}
        />
      </label>
      <label className="settings__field">
        <span>{t("providerForm.displayName")}</span>
        <input
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder={t("providerForm.displayNamePlaceholder")}
        />
      </label>
      <label className="settings__field">
        <span>{isOllama ? t("providerForm.ollamaBaseUrl") : t("providerForm.baseUrl")}</span>
        <input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder={isOllama ? "http://127.0.0.1:11434" : "https://api.example.com/v1"}
        />
      </label>
      <label className="settings__field">
        <span>{t("providerForm.model")}</span>
        <input
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder={
            isOllama
              ? t("providerForm.modelPlaceholderOllama")
              : t("providerForm.modelPlaceholderOpenAi")
          }
        />
      </label>
      {!isOllama ? (
        <label className="settings__field">
          <span>{t("providerForm.apiKey")}</span>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={isEdit ? t("providerForm.apiKeyEditPlaceholder") : "sk-..."}
          />
        </label>
      ) : null}
      {error ? <p className="settings__error">{error}</p> : null}
      <div className="settings__actions">
        <button type="button" className="btn btn--ghost" onClick={onCancel}>
          {t("common.cancel")}
        </button>
        <button type="submit" className="btn" disabled={busy}>
          {busy ? t("providerForm.saving") : t("common.save")}
        </button>
      </div>
    </form>
  );
}
