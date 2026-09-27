/**
 * 引导式模型配置：用户只需选择厂商、填写模型名和 Key。
 * 协议与端点来自服务端目录；高级用户仍可覆盖。提交由服务端一次性测试并保存。
 */
import { useMemo, useState, type FormEvent } from "react";
import {
  configApi,
  type ModelConfigureInput,
  type ModelProfileSummary,
  type ProviderPreset,
  type WireProtocol,
} from "../api/configClient";
import { useI18n } from "../i18n";

interface ProviderFormProps {
  presets: ProviderPreset[];
  profiles: ModelProfileSummary[];
  initial?: ModelProfileSummary;
  onSaved: (profile: ModelProfileSummary) => Promise<void> | void;
  onCancel: () => void;
}

const NEW_CONNECTION = "__new__";

export function safeId(value: string, fallback: string): string {
  const normalized = value
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  return normalized || fallback;
}

export function uniqueId(seed: string, used: Set<string>, current?: string): string {
  const base = safeId(seed, "model");
  if (base === current || !used.has(base)) return base;
  for (let index = 2; ; index += 1) {
    const candidate = `${base}-${index}`;
    if (candidate === current || !used.has(candidate)) return candidate;
  }
}

export function ProviderForm({ presets, profiles, initial, onSaved, onCancel }: ProviderFormProps) {
  const { t } = useI18n();
  const isEdit = initial !== undefined;
  const initialPreset = presets.find((preset) => preset.id === initial?.presetId) ?? presets[0];
  const [connectionChoice, setConnectionChoice] = useState(initial?.connectionId ?? NEW_CONNECTION);
  const [presetId, setPresetId] = useState(initialPreset?.id ?? "custom");
  const [protocol, setProtocol] = useState<WireProtocol>(
    initial?.protocol ?? initialPreset?.recommendedProtocol ?? "openai_chat",
  );
  const [profileName, setProfileName] = useState(initial?.displayName ?? "");
  const [model, setModel] = useState(initial?.model ?? "");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(initial?.baseUrl ?? "");
  const [contextWindow, setContextWindow] = useState(
    initial?.contextWindow ? String(initial.contextWindow) : "",
  );
  const [advanced, setAdvanced] = useState(initial?.presetId === "custom");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const connections = useMemo(() => {
    const byId = new Map<string, ModelProfileSummary>();
    for (const profile of profiles) byId.set(profile.connectionId, profile);
    return [...byId.values()];
  }, [profiles]);

  const reusedConnection = connections.find((item) => item.connectionId === connectionChoice);
  const selectedPreset =
    presets.find((preset) => preset.id === (reusedConnection?.presetId ?? presetId)) ?? presets[0];
  const needsKey = selectedPreset?.authKind === "api_key";
  const endpoint = baseUrl || selectedPreset?.defaultEndpoints[protocol] || "";

  function selectPreset(nextId: string) {
    const next = presets.find((preset) => preset.id === nextId);
    if (!next) return;
    setPresetId(next.id);
    setProtocol(next.recommendedProtocol);
    setBaseUrl(next.defaultEndpoints[next.recommendedProtocol] ?? "");
    setAdvanced(next.id === "custom");
  }

  function selectConnection(nextId: string) {
    setConnectionChoice(nextId);
    const existing = connections.find((item) => item.connectionId === nextId);
    if (!existing) return;
    setPresetId(existing.presetId);
    setProtocol(existing.protocol);
    setBaseUrl(existing.baseUrl ?? "");
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!selectedPreset) {
      setError(t("providerForm.errPreset"));
      return;
    }
    if (!model.trim()) {
      setError(t("providerForm.errModel"));
      return;
    }
    if (!reusedConnection && needsKey && !apiKey.trim() && !initial?.maskedKey) {
      setError(t("providerForm.errApiKey"));
      return;
    }
    if (selectedPreset.id === "custom" && !endpoint.trim()) {
      setError(t("providerForm.errBaseUrl"));
      return;
    }

    const usedProfiles = new Set(profiles.map((item) => item.id));
    const usedConnections = new Set(profiles.map((item) => item.connectionId));
    const finalProfileId = initial?.id ?? uniqueId(`${selectedPreset.id}-${model}`, usedProfiles);
    const finalConnectionId =
      initial?.connectionId ??
      reusedConnection?.connectionId ??
      uniqueId(selectedPreset.id, usedConnections);
    const body: ModelConfigureInput = {
      profileId: finalProfileId,
      connectionId: finalConnectionId,
      presetId: selectedPreset.id,
      connectionName: reusedConnection?.connectionName ?? selectedPreset.displayName,
      profileName: profileName.trim() || model.trim(),
      protocol,
      model: model.trim(),
      baseUrl: endpoint.trim() || undefined,
      apiKey: reusedConnection && !isEdit ? undefined : apiKey.trim() || undefined,
      contextWindow: contextWindow ? Number(contextWindow) : undefined,
    };

    setBusy(true);
    try {
      const result = await configApi.configureModel(body);
      if (!result.ok || !result.profile) {
        setError(result.hint ?? t("settings.unknownReason"));
        return;
      }
      await onSaved(result.profile);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("providerForm.errSave"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="settings__form" onSubmit={handleSubmit}>
      {!isEdit && connections.length > 0 ? (
        <label className="settings__field">
          <span>{t("providerForm.connection")}</span>
          <select
            value={connectionChoice}
            onChange={(event) => selectConnection(event.target.value)}
          >
            <option value={NEW_CONNECTION}>{t("providerForm.newConnection")}</option>
            {connections.map((connection) => (
              <option key={connection.connectionId} value={connection.connectionId}>
                {t("providerForm.reuseConnection", { name: connection.connectionName })}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {!reusedConnection || isEdit ? (
        <label className="settings__field">
          <span>{t("providerForm.provider")}</span>
          <select
            value={selectedPreset?.id}
            onChange={(event) => selectPreset(event.target.value)}
            disabled={isEdit}
          >
            {presets.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.displayName}
              </option>
            ))}
          </select>
          {selectedPreset ? <small>{selectedPreset.description}</small> : null}
        </label>
      ) : null}

      <label className="settings__field">
        <span>{t("providerForm.model")}</span>
        <input
          value={model}
          onChange={(event) => setModel(event.target.value)}
          placeholder={selectedPreset?.modelPlaceholder}
          autoFocus
        />
      </label>

      <label className="settings__field">
        <span>{t("providerForm.profileName")}</span>
        <input
          value={profileName}
          onChange={(event) => setProfileName(event.target.value)}
          placeholder={model || t("providerForm.profileNamePlaceholder")}
        />
      </label>

      {needsKey && (!reusedConnection || isEdit) ? (
        <label className="settings__field">
          <span>{t("providerForm.apiKey")}</span>
          <input
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={isEdit ? t("providerForm.apiKeyEditPlaceholder") : "sk-..."}
            autoComplete="off"
          />
        </label>
      ) : null}

      <button
        type="button"
        className="btn btn--ghost"
        onClick={() => setAdvanced((value) => !value)}
      >
        {advanced ? t("providerForm.hideAdvanced") : t("providerForm.showAdvanced")}
      </button>

      {advanced ? (
        <>
          <label className="settings__field">
            <span>{t("providerForm.protocol")}</span>
            <select
              value={protocol}
              onChange={(event) => {
                const next = event.target.value as WireProtocol;
                setProtocol(next);
                setBaseUrl(selectedPreset?.defaultEndpoints[next] ?? "");
              }}
            >
              {selectedPreset?.protocols.map((item) => (
                <option key={item} value={item}>
                  {t(`providerForm.protocol.${item}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="settings__field">
            <span>{t("providerForm.baseUrl")}</span>
            <input value={endpoint} onChange={(event) => setBaseUrl(event.target.value)} />
          </label>
          <label className="settings__field">
            <span>{t("providerForm.contextWindow")}</span>
            <input
              type="number"
              min="1"
              value={contextWindow}
              onChange={(event) => setContextWindow(event.target.value)}
              placeholder={t("providerForm.contextWindowPlaceholder")}
            />
          </label>
        </>
      ) : null}

      {error ? <p className="settings__error">{error}</p> : null}
      <p className="settings__hint">{t("providerForm.testAndSaveHint")}</p>
      <div className="settings__actions">
        <button type="button" className="btn btn--ghost" onClick={onCancel} disabled={busy}>
          {t("common.cancel")}
        </button>
        <button type="submit" className="btn" disabled={busy}>
          {busy ? t("providerForm.testingAndSaving") : t("providerForm.testAndSave")}
        </button>
      </div>
    </form>
  );
}
