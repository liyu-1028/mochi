/**
 * ProviderForm —— 新增模型提供方的极简表单（纯受控组件，无表单库）。
 */
import { useState, type FormEvent } from "react";
import type { ProviderCreateInput, ProviderKind } from "../api/configClient";

interface ProviderFormProps {
  onSubmit: (input: ProviderCreateInput) => Promise<void>;
  onCancel: () => void;
}

const ID_PATTERN = /^[a-z0-9][a-z0-9_-]*$/;

export function ProviderForm({ onSubmit, onCancel }: ProviderFormProps) {
  const [kind, setKind] = useState<ProviderKind>("openai_compatible");
  const [id, setId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isOllama = kind === "ollama";

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (!ID_PATTERN.test(id)) {
      setError("ID 仅限小写字母/数字/下划线/连字符，且以字母数字开头");
      return;
    }
    if (!model.trim()) {
      setError("请填写模型名称");
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
      setError(err instanceof Error ? err.message : "保存失败");
      setBusy(false);
    }
  }

  return (
    <form className="settings__form" onSubmit={handleSubmit}>
      <label className="settings__field">
        <span>类型</span>
        <select value={kind} onChange={(e) => setKind(e.target.value as ProviderKind)}>
          <option value="openai_compatible">OpenAI 兼容接口</option>
          <option value="ollama">Ollama（本地）</option>
          <option value="anthropic">Anthropic（M1 支持）</option>
        </select>
      </label>
      <label className="settings__field">
        <span>ID（唯一标识）</span>
        <input value={id} onChange={(e) => setId(e.target.value)} placeholder="如 deepseek" />
      </label>
      <label className="settings__field">
        <span>显示名称</span>
        <input
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="如 我的云端模型"
        />
      </label>
      <label className="settings__field">
        <span>{isOllama ? "服务地址（默认 127.0.0.1:11434）" : "Base URL"}</span>
        <input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder={isOllama ? "http://127.0.0.1:11434" : "https://api.example.com/v1"}
        />
      </label>
      <label className="settings__field">
        <span>模型</span>
        <input
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder={isOllama ? "如 qwen3:8b" : "如 gpt-4o-mini"}
        />
      </label>
      {!isOllama ? (
        <label className="settings__field">
          <span>API Key（存入系统钥匙串，不落文件）</span>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-..."
          />
        </label>
      ) : null}
      {error ? <p className="settings__error">{error}</p> : null}
      <div className="settings__actions">
        <button type="button" className="btn btn--ghost" onClick={onCancel}>
          取消
        </button>
        <button type="submit" className="btn" disabled={busy}>
          {busy ? "保存中…" : "保存"}
        </button>
      </div>
    </form>
  );
}
