/**
 * SettingsVoiceSection —— 设置「语音」tab（M1-S2，功能清单 5.1/7.1）。
 *
 * 事实源在 sidecar [voice]：改值即 putVoice 落盘热生效；静音/启用翻转
 * 经 voiceEvents 通知 useTTS 立即停播。试听共用 speakText 播放链路。
 */
import { useEffect, useState } from "react";
import { configApi, type VoiceSettings } from "../api/configClient";
import { ttsApi, type TtsVoiceOption } from "../api/ttsClient";
import { speakText } from "../hooks/useTTS";
import { useI18n } from "../i18n";
import { notifyVoiceChanged } from "../store/voiceEvents";

export function SettingsVoiceSection() {
  const { t } = useI18n();
  const [voice, setVoice] = useState<VoiceSettings | null>(null);
  const [voices, setVoices] = useState<TtsVoiceOption[]>([]);

  useEffect(() => {
    configApi
      .getVoice()
      .then(setVoice)
      .catch(() => {});
    ttsApi
      .voices()
      .then((v) => setVoices(v.voices))
      .catch(() => {});
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

  if (!voice) return null;

  return (
    <div className="settings__voice">
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
          {(voices.length > 0
            ? voices
            : [{ id: voice.voiceId, name: voice.voiceId, lang: "", gender: "" }]
          ).map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
              {v.lang ? `（${v.lang}）` : ""}
            </option>
          ))}
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
        <button className="btn btn--ghost" onClick={() => void speakText(t("voice.testText"))}>
          {t("voice.test")}
        </button>
      </div>
      <p className="settings__hint">{t("voice.hint")}</p>
    </div>
  );
}
