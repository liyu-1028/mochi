/**
 * OnboardingWizard —— 首次运行的模型来源选择（功能清单 1.5 的模型选择步预留）。
 *
 * 无 provider 时展示三分支：
 * 1. 探测到 Ollama → 一键启用本地模型（Zero Config 核心路径）
 * 2. 填入 Key → 打开设置面板
 * 3. 试用模式 → 直接开始（echo 桩）
 */
import { useEffect, useState } from "react";
import { configApi, type OllamaStatus } from "../api/configClient";
import { useI18n } from "../i18n";

interface OnboardingWizardProps {
  onDone: () => void;
  onOpenSettings: () => void;
}

export function OnboardingWizard({ onDone, onOpenSettings }: OnboardingWizardProps) {
  const { t } = useI18n();
  const [ollama, setOllama] = useState<OllamaStatus | null>(null);
  const [checking, setChecking] = useState(true);
  const [enabling, setEnabling] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // 已有 provider → 不需要引导
      try {
        const providers = await configApi.listProviders();
        if (!cancelled && providers.length > 0) {
          onDone();
          return;
        }
        const status = await configApi.ollamaStatus();
        if (!cancelled) setOllama(status);
      } catch {
        // sidecar 未就绪：WS 重连机制会接住，这里保持试用分支
      } finally {
        if (!cancelled) setChecking(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [onDone]);

  async function enableOllama() {
    if (!ollama || ollama.models.length === 0) return;
    setEnabling(true);
    try {
      await configApi.createProvider({
        id: "ollama",
        kind: "ollama",
        displayName: "Ollama（本地）",
        baseUrl: "http://127.0.0.1:11434",
        model: ollama.models[0],
      });
      await configApi.setDefault("ollama");
      onDone();
    } catch {
      setEnabling(false);
    }
  }

  return (
    <div className="settings-overlay">
      <div className="settings settings--wizard">
        <header className="settings__header">
          <h2>{t("onboarding.welcome")}</h2>
        </header>
        {checking ? (
          <p className="settings__feedback">{t("onboarding.searching")}</p>
        ) : (
          <>
            {ollama?.available && ollama.models.length > 0 ? (
              <button
                className="btn settings__wizard-main"
                onClick={enableOllama}
                disabled={enabling}
              >
                {enabling
                  ? t("onboarding.enabling")
                  : t("onboarding.enableOllama", { model: ollama.models[0] })}
              </button>
            ) : (
              <p className="settings__item-sub">{ollama?.errorHint ?? t("onboarding.noOllama")}</p>
            )}
            <div className="settings__actions">
              <button
                className="btn btn--ghost"
                onClick={() => {
                  onOpenSettings();
                  onDone();
                }}
              >
                {t("onboarding.fillKey")}
              </button>
              <button className="btn btn--ghost" onClick={onDone}>
                {t("onboarding.useTrial")}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
