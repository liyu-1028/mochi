/**
 * SettingsPanel —— 模型设置模态面板（M0-S2，功能清单 6.3/7.2 的最小可用入口）。
 *
 * 能力：provider 列表 / 新增 / 连通性测试 / 设为默认 / 删除 / 试用模式切换。
 * 切换默认即热生效（sidecar registry 按回合解析），无需重启。
 */
import { useCallback, useEffect, useState } from "react";
import {
  TRIAL_PROVIDER_ID,
  configApi,
  type ProviderCreateInput,
  type ProviderSummary,
} from "../api/configClient";
import { ProviderForm } from "./ProviderForm";

interface SettingsPanelProps {
  onClose: () => void;
}

const KIND_LABEL: Record<string, string> = {
  ollama: "Ollama 本地",
  openai_compatible: "OpenAI 兼容",
  anthropic: "Anthropic",
};

export function SettingsPanel({ onClose }: SettingsPanelProps) {
  const [providers, setProviders] = useState<ProviderSummary[]>([]);
  const [defaultId, setDefaultId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await configApi.listProviders();
      setProviders(list);
      setDefaultId(list.find((p) => p.isDefault)?.id ?? null);
    } catch {
      setFeedback("无法连接 sidecar 配置服务，请确认它正在运行");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleCreate(input: ProviderCreateInput) {
    await configApi.createProvider(input);
    setShowForm(false);
    setFeedback(`已添加「${input.displayName}」`);
    await refresh();
  }

  async function handleTest(id: string) {
    setBusyId(id);
    setFeedback(null);
    try {
      const result = await configApi.testProvider(id);
      setFeedback(
        result.ok ? `「${id}」连接成功 ✓` : `「${id}」暂不可用：${result.hint ?? "未知原因"}`,
      );
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "测试失败");
    } finally {
      setBusyId(null);
    }
  }

  async function handleSetDefault(id: string) {
    await configApi.setDefault(id);
    setFeedback(`已切换到「${id}」，立即生效`);
    await refresh();
  }

  async function handleDelete(id: string) {
    await configApi.deleteProvider(id);
    setFeedback(`已删除「${id}」`);
    await refresh();
  }

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings" onClick={(e) => e.stopPropagation()}>
        <header className="settings__header">
          <h2>模型设置</h2>
          <button className="settings__close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        {feedback ? <p className="settings__feedback">{feedback}</p> : null}

        <ul className="settings__list">
          <li className="settings__item">
            <div className="settings__item-main">
              <strong>试用模式</strong>
              <span className="settings__item-sub">内置 echo 桩，无需任何 Key</span>
            </div>
            {defaultId === TRIAL_PROVIDER_ID ? (
              <span className="settings__tag">使用中</span>
            ) : (
              <button
                className="btn btn--ghost"
                onClick={() => handleSetDefault(TRIAL_PROVIDER_ID)}
              >
                设为默认
              </button>
            )}
          </li>
          {providers.map((p) => (
            <li key={p.id} className="settings__item">
              <div className="settings__item-main">
                <strong>{p.displayName}</strong>
                <span className="settings__item-sub">
                  {KIND_LABEL[p.kind] ?? p.kind} · {p.model}
                  {p.maskedKey ? ` · Key ${p.maskedKey}` : ""}
                </span>
              </div>
              <div className="settings__item-actions">
                <button
                  className="btn btn--ghost"
                  disabled={busyId === p.id}
                  onClick={() => handleTest(p.id)}
                >
                  {busyId === p.id ? "测试中…" : "测试"}
                </button>
                {p.isDefault ? (
                  <span className="settings__tag">使用中</span>
                ) : (
                  <button className="btn btn--ghost" onClick={() => handleSetDefault(p.id)}>
                    设为默认
                  </button>
                )}
                <button
                  className="btn btn--ghost settings__danger"
                  onClick={() => handleDelete(p.id)}
                >
                  删除
                </button>
              </div>
            </li>
          ))}
        </ul>

        {showForm ? (
          <ProviderForm onSubmit={handleCreate} onCancel={() => setShowForm(false)} />
        ) : (
          <button className="btn" onClick={() => setShowForm(true)}>
            + 添加模型提供方
          </button>
        )}
      </div>
    </div>
  );
}
