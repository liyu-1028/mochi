/**
 * SettingsAgentSection —— 设置「角色」tab 里的认知行为区块（2026-09-28）。
 *
 * 事实源在 sidecar [agent]：maxReplyChars（单回合回复文本上限，50–4000）
 * 即时落盘热生效（下一回合 agent 重建即用新值）。超限由服务端截断 +「…」，
 * 且 system prompt 同步告知模型真实上限。
 */
import { useEffect, useState } from "react";
import { configApi, type AgentSettings } from "../api/configClient";
import { useI18n } from "../i18n";

/** 纯函数：输入框字符串 → 合法值或 null（50–4000 整数）。 */
export function parseMaxReplyChars(raw: string): number | null {
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 50 || n > 4000) return null;
  return n;
}

export function SettingsAgentSection() {
  const { t } = useI18n();
  const [agent, setAgent] = useState<AgentSettings | null>(null);
  /** 输入框暂存态（字符串），失焦/回车提交；非法值红框提示不提交 */
  const [draft, setDraft] = useState("");
  const [invalid, setInvalid] = useState(false);

  useEffect(() => {
    configApi
      .getAgent()
      .then((a) => {
        setAgent(a);
        setDraft(String(a.maxReplyChars));
      })
      .catch(() => {});
  }, []);

  async function commit() {
    if (!agent) return;
    const value = parseMaxReplyChars(draft);
    if (value === null) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    const next = { ...agent, maxReplyChars: value };
    setAgent(next); // 乐观更新，失败回拉
    try {
      const saved = await configApi.putAgent({ maxReplyChars: value });
      setAgent(saved);
    } catch {
      configApi
        .getAgent()
        .then((a) => {
          setAgent(a);
          setDraft(String(a.maxReplyChars));
        })
        .catch(() => {});
    }
  }

  if (!agent) return null;

  return (
    <div className="settings__agent">
      <label className="settings__field">
        <span>{t("agent.maxReplyChars")}</span>
        <input
          type="number"
          min={50}
          max={4000}
          step={50}
          value={draft}
          aria-invalid={invalid}
          onChange={(e) => {
            setDraft(e.target.value);
            setInvalid(false);
          }}
          onBlur={() => void commit()}
          onKeyDown={(e) => {
            if (e.key === "Enter") void commit();
          }}
        />
      </label>
      <p className={`settings__hint${invalid ? " settings__hint--error" : ""}`}>
        {invalid ? t("agent.maxReplyCharsInvalid") : t("agent.maxReplyCharsHint")}
      </p>
    </div>
  );
}
