/**
 * SettingsVoiceSection —— 设置「语音」tab（ADR-0007-R1 云端引擎）。
 *
 * 顶部引擎状态区：未配置引导录入/复用百炼连接（真实合成探测）；
 * 已配置展示脱敏 Key 与测试/解绑。设置项事实源在 sidecar [voice]。
 */
import { useEffect, useState, type ReactNode } from "react";
import { configApi, type VoiceConnectionStatus, type VoiceSettings } from "../api/configClient";
import { ttsApi, type TtsVoiceOption } from "../api/ttsClient";
import { speakText } from "../hooks/useTTS";
import { useI18n } from "../i18n";
import { notifyVoiceChanged, voiceEvents } from "../store/voiceEvents";

/** setup 请求参数：复用连接优先，其次新 Key；两者皆空返回 null（按钮禁用兜底）。 */
export function buildSetupInput(
  apiKey: string,
  reuseId: string,
): { apiKey: string } | { reuseConnectionId: string } | null {
  if (reuseId) return { reuseConnectionId: reuseId };
  if (apiKey) return { apiKey };
  return null;
}

/** 音色目录按品类 optgroup 分组渲染；无 category 的平铺（默认兜底项也走这里）。 */
export function renderVoiceOptions(
  options: TtsVoiceOption[],
  t: (key: string) => string,
): ReactNode[] {
  const groups = new Map<string, TtsVoiceOption[]>();
  const plain: TtsVoiceOption[] = [];
  for (const v of options) {
    if (v.category) groups.set(v.category, [...(groups.get(v.category) ?? []), v]);
    else plain.push(v);
  }
  const renderOption = (v: TtsVoiceOption) => (
    <option key={v.id} value={v.id}>
      {`${v.name}${v.lang && v.lang !== "zh-CN" ? `（${v.lang}）` : ""}`}
    </option>
  );
  return [
    ...[...groups.entries()].map(([category, items]) => (
      <optgroup key={category} label={t(`voice.category.${category}`)}>
        {items.map(renderOption)}
      </optgroup>
    )),
    ...plain.map(renderOption),
  ];
}

export function SettingsVoiceSection() {
  const { t } = useI18n();
  const [voice, setVoice] = useState<VoiceSettings | null>(null);
  const [voices, setVoices] = useState<TtsVoiceOption[]>([]);
  const [status, setStatus] = useState<VoiceConnectionStatus | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [reuseId, setReuseId] = useState("");
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; text: string } | null>(null);

  const reload = () => {
    configApi
      .getVoice()
      .then(setVoice)
      .catch(() => {});
    ttsApi
      .voices()
      .then((v) => setVoices(v.voices))
      .catch(() => {});
    configApi
      .voiceStatus()
      .then(setStatus)
      .catch(() => {});
  };
  useEffect(() => {
    reload();
    voiceEvents.addEventListener("voice-changed", reload);
    return () => voiceEvents.removeEventListener("voice-changed", reload);
  }, []);

  async function update(patch: Partial<VoiceSettings>) {
    if (!voice) return;
    const next = { ...voice, ...patch };
    setVoice(next); // 乐观更新，失败回拉
    try {
      const saved = await configApi.putVoice(patch);
      setVoice(saved);
      notifyVoiceChanged();
    } catch {
      configApi
        .getVoice()
        .then(setVoice)
        .catch(() => {});
    }
  }

  async function setupConnection() {
    setBusy(true);
    setFeedback(null);
    try {
      const input = buildSetupInput(apiKey, reuseId);
      if (!input) return;
      const result = await configApi.setupVoiceConnection(input);
      if (result.ok) {
        setFeedback({ ok: true, text: t("voice.setupOk") });
        setApiKey("");
        reload();
        notifyVoiceChanged();
      } else {
        setFeedback({ ok: false, text: t("voice.setupFail") });
      }
    } catch {
      setFeedback({ ok: false, text: t("voice.setupFail") });
    } finally {
      setBusy(false);
    }
  }

  async function testConnection() {
    setBusy(true);
    setFeedback(null);
    try {
      const outcome = await speakText(t("voice.testText"));
      setFeedback({
        ok: outcome === "played",
        text: t(outcome === "played" ? "voice.setupOk" : "voice.setupFail"),
      });
    } catch {
      setFeedback({ ok: false, text: t("voice.setupFail") });
    } finally {
      setBusy(false);
    }
  }

  if (!voice) return null;

  return (
    <div className="settings__voice">
      <section className="settings__field" aria-label={t("voice.engine")}>
        <span>{t("voice.engine")}</span>
        {status?.configured ? (
          <div className="settings__item">
            <strong>百炼 · {status.displayName}</strong>
            <span className="settings__item-sub">
              {status.maskedKey ? `Key ${status.maskedKey}` : ""}
            </span>
            <div className="settings__item-actions">
              <button
                className="btn btn--ghost"
                disabled={busy}
                onClick={() => void testConnection()}
              >
                {t("voice.testConnection")}
              </button>
              <button
                className="btn btn--ghost"
                onClick={() => {
                  void update({ connectionId: null, ttsEnabled: false });
                  reload();
                }}
              >
                {t("voice.unbind")}
              </button>
            </div>
          </div>
        ) : (
          <div className="settings__item">
            <small className="settings__hint">{t("voice.unconfiguredHint")}</small>
            <label className="settings__field">
              <span>{t("voice.apiKeyLabel")}</span>
              <input
                type="password"
                value={apiKey}
                placeholder={t("voice.apiKeyPlaceholder")}
                onChange={(e) => setApiKey(e.target.value)}
                aria-label={t("voice.apiKeyLabel")}
              />
            </label>
            {(status?.reusable.length ?? 0) > 0 ? (
              <label className="settings__field">
                <span>{t("voice.useExistingConnection")}</span>
                <select
                  value={reuseId}
                  onChange={(e) => setReuseId(e.target.value)}
                  aria-label={t("voice.useExistingConnection")}
                >
                  <option value="">—</option>
                  {status?.reusable.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.displayName} · {r.maskedKey}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <button
              className="btn"
              disabled={busy || (!reuseId && !apiKey)}
              onClick={() => void setupConnection()}
            >
              {busy ? t("voice.setupTesting") : t("voice.setupButton")}
            </button>
          </div>
        )}
        {feedback ? (
          <small className="settings__hint" role={feedback.ok ? "status" : "alert"}>
            {feedback.text}
          </small>
        ) : null}
      </section>

      <label className="settings__field">
        <span>{t("voice.enabled")}</span>
        <input
          type="checkbox"
          checked={voice.ttsEnabled}
          onChange={(e) => void update({ ttsEnabled: e.target.checked })}
        />
      </label>
      <label className="settings__field">
        <span>{t("voice.muted")}</span>
        <input
          type="checkbox"
          checked={voice.muted}
          onChange={(e) => void update({ muted: e.target.checked })}
        />
      </label>
      <label className="settings__field">
        <span>{t("voice.voice")}</span>
        <select
          value={voice.voiceId}
          onChange={(e) => void update({ voiceId: e.target.value })}
          aria-label={t("voice.voice")}
        >
          {renderVoiceOptions(
            voices.length > 0
              ? voices
              : [{ id: voice.voiceId, name: voice.voiceId, lang: "", gender: "" }],
            t,
          )}
        </select>
      </label>
      <label className="settings__field">
        <span>{t("voice.volume")}</span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={voice.volume}
          onChange={(e) => void update({ volume: Number(e.target.value) })}
          aria-label={t("voice.volume")}
        />
      </label>
      <label className="settings__field">
        <span>{t("voice.rate")}</span>
        <input
          type="range"
          min={0.5}
          max={2}
          step={0.1}
          value={voice.rate}
          onChange={(e) => void update({ rate: Number(e.target.value) })}
          aria-label={t("voice.rate")}
        />
      </label>
      <div className="settings__field">
        <button
          className="btn btn--ghost"
          onClick={() =>
            void speakText(t("voice.testText"), { voiceId: voice.voiceId, rate: voice.rate })
          }
        >
          {t("voice.test")}
        </button>
      </div>
      <p className="settings__hint">{t("voice.asrHint")}</p>
      <p className="settings__hint">{t("voice.hint")}</p>
    </div>
  );
}
