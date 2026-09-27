/**
 * ProviderForm —— 模型提供方的新增/编辑表单（纯受控组件，无表单库）。
 *
 * - 无 initial：新增模式，提交完整 ProviderCreateInput；
 * - 有 initial：编辑模式，回填现有值；id 与类型锁定
 *   （后端 PUT 不支持改 kind/id，换类型请删除后重建）；
 *   API Key 留空 = 保留原 Key 不变。
 * - 保存门禁（功能清单 7.2）：必须先点「测试」且通过，保存才可用；
 *   连接相关字段（类型/地址/模型/Key）任一变更即重置测试状态。
 *   测试走 test-draft 端点：不落盘、不写钥匙串。
 */
import { useState, type FormEvent } from "react";
import type { ProviderCreateInput, ProviderKind, ProviderSummary } from "../api/configClient";
import { configApi } from "../api/configClient";
import { useI18n } from "../i18n";

interface ProviderFormProps {
  /** 传入已有 provider 时进入编辑模式。 */
  initial?: ProviderSummary;
  onSubmit: (input: ProviderCreateInput) => Promise<void>;
  onCancel: () => void;
}

const ID_PATTERN = /^[a-z0-9][a-z0-9_-]*$/;

type TestState = "idle" | "running" | "passed" | "failed";

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
  const [testState, setTestState] = useState<TestState>("idle");
  const [testHint, setTestHint] = useState<string | null>(null);

  const isOllama = kind === "ollama";
  /** 连接相关字段变更 → 已通过的测试失效，须重测。 */
  function invalidateTest() {
    setTestState((prev) => (prev === "idle" || prev === "running" ? prev : "idle"));
    setTestHint(null);
  }

  async function handleTest() {
    if (!model.trim()) {
      setTestState("failed");
      setTestHint(t("providerForm.errModel"));
      return;
    }
    setError(null);
    setTestState("running");
    setTestHint(null);
    try {
      const result = await configApi.testProviderDraft({
        id: isEdit ? initial.id : undefined,
        kind,
        baseUrl: baseUrl.trim() || undefined,
        model: model.trim(),
        apiKey: isOllama || !apiKey.trim() ? undefined : apiKey.trim(),
      });
      if (result.ok) {
        setTestState("passed");
      } else {
        setTestState("failed");
        setTestHint(result.hint ?? t("settings.unknownReason"));
      }
    } catch (err) {
      setTestState("failed");
      setTestHint(err instanceof Error ? err.message : t("settings.testError"));
    }
  }

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
          onChange={(e) => {
            setKind(e.target.value as ProviderKind);
            invalidateTest();
          }}
          disabled={isEdit}
        >
          <option value="openai_compatible">{t("providerForm.kindOpenAi")}</option>
          <option value="openai_responses">{t("providerForm.kindOpenAiResponses")}</option>
          <option value="anthropic">{t("providerForm.kindAnthropic")}</option>
          <option value="ollama">{t("providerForm.kindOllama")}</option>
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
          onChange={(e) => {
            setBaseUrl(e.target.value);
            invalidateTest();
          }}
          placeholder={
            isOllama
              ? "http://127.0.0.1:11434"
              : kind === "openai_responses"
                ? "https://api.openai.com/v1"
                : "https://api.example.com/v1"
          }
        />
      </label>
      {kind === "openai_responses" ? (
        <p className="settings__hint">{t("providerForm.responsesBaseUrlHint")}</p>
      ) : null}
      <label className="settings__field">
        <span>{t("providerForm.model")}</span>
        <input
          value={model}
          onChange={(e) => {
            setModel(e.target.value);
            invalidateTest();
          }}
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
            onChange={(e) => {
              setApiKey(e.target.value);
              invalidateTest();
            }}
            placeholder={isEdit ? t("providerForm.apiKeyEditPlaceholder") : "sk-..."}
          />
        </label>
      ) : null}
      {testHint ? <p className="settings__error">{testHint}</p> : null}
      {testState === "passed" ? (
        <p className="settings__feedback">{t("providerForm.testPassed")}</p>
      ) : null}
      {error ? <p className="settings__error">{error}</p> : null}
      <div className="settings__actions">
        <button type="button" className="btn btn--ghost" onClick={onCancel}>
          {t("common.cancel")}
        </button>
        {/* 保存门禁：测试通过前不可保存 */}
        <button
          type="button"
          className="btn btn--ghost"
          disabled={testState === "running" || busy}
          onClick={() => void handleTest()}
        >
          {testState === "running" ? t("providerForm.testing") : t("providerForm.test")}
        </button>
        <button
          type="submit"
          className="btn"
          disabled={busy || testState !== "passed"}
          title={testState !== "passed" ? t("providerForm.saveNeedsTest") : undefined}
        >
          {busy ? t("providerForm.saving") : t("common.save")}
        </button>
      </div>
    </form>
  );
}
