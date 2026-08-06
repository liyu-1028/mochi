/**
 * PersonaSection —— 设置「角色」tab：人格选择（功能清单 6.13，ADR-0005）。
 *
 * 三维度（灵魂/性格/说话风格）各提供预设卡片单选 +「自定义」文本输入；
 * 维度间任意组合。本地编辑态 + 显式保存（一次 PUT 全量），另有恢复默认。
 * 预设目录与当前配置一次 GET 拉齐；保存经 registry 缓存失效下一回合生效。
 *
 * 纯函数（draftFromSettings/selectPreset/selectCustom/buildPersonaPayload/
 * personaDirty）导出供 vitest 直测（node 环境无组件渲染，仓库惯例）。
 */
import { useCallback, useEffect, useState } from "react";
import {
  configApi,
  type PersonaDimension,
  type PersonaPreset,
  type PersonaSettings,
} from "../api/configClient";
import { useI18n } from "../i18n";

/** 自定义文本上限（与后端 PersonaConfig max_length 一致）。 */
export const PERSONA_CUSTOM_MAX = 500;

/** 单维度编辑态：预设 id 与自定义文本互斥（customSelected 标记自定义模式）。 */
export interface DimensionDraft {
  presetId: string;
  customText: string;
  customSelected: boolean;
}

export type PersonaDrafts = Record<PersonaDimension, DimensionDraft>;

const DIMENSIONS: PersonaDimension[] = ["soul", "personality", "style"];

/** 服务端配置 → 编辑态：custom 非空即自定义模式（与服务端 custom 优先一致）。 */
export function draftFromSettings(preset: string, custom: string): DimensionDraft {
  if (custom.trim() !== "") {
    return { presetId: preset, customText: custom, customSelected: true };
  }
  return { presetId: preset, customText: "", customSelected: false };
}

/** 选中预设卡：清除自定义（互斥）。 */
export function selectPreset(draft: DimensionDraft, presetId: string): DimensionDraft {
  return { ...draft, presetId, customText: "", customSelected: false };
}

/** 选中自定义卡：清除预设（互斥），保留已输入文本。 */
export function selectCustom(draft: DimensionDraft): DimensionDraft {
  return { presetId: "", customSelected: true, customText: draft.customText };
}

/** 编辑态 → PUT 字段对（custom 模式下 preset 清空）。 */
export function dimensionToPayload(draft: DimensionDraft): { preset: string; custom: string } {
  if (draft.customSelected) {
    return { preset: "", custom: draft.customText.trim() };
  }
  return { preset: draft.presetId, custom: "" };
}

/** 三维度编辑态 → 全量 PUT body。 */
export function buildPersonaPayload(drafts: PersonaDrafts): PersonaSettings {
  const soul = dimensionToPayload(drafts.soul);
  const personality = dimensionToPayload(drafts.personality);
  const style = dimensionToPayload(drafts.style);
  return {
    soulPreset: soul.preset,
    soulCustom: soul.custom,
    personalityPreset: personality.preset,
    personalityCustom: personality.custom,
    stylePreset: style.preset,
    styleCustom: style.custom,
  };
}

/** dirty 判定：编辑态与初始配置是否一致（决定保存按钮可用性）。 */
export function personaDirty(initial: PersonaSettings, drafts: PersonaDrafts): boolean {
  return JSON.stringify(buildPersonaPayload(drafts)) !== JSON.stringify(initial);
}

/** 预设展示名/描述按当前语言回退 zh-CN，再回退 id（防缺语言键）。 */
export function presetLabel(
  preset: PersonaPreset,
  locale: string,
  field: "name" | "description",
): string {
  return preset[field][locale] ?? preset[field]["zh-CN"] ?? preset.id;
}

/** 空人格草稿（恢复默认用）。 */
export function emptyDrafts(): PersonaDrafts {
  const empty: DimensionDraft = { presetId: "", customText: "", customSelected: false };
  return { soul: { ...empty }, personality: { ...empty }, style: { ...empty } };
}

export function PersonaSection() {
  const { t, locale } = useI18n();
  const [presets, setPresets] = useState<Record<PersonaDimension, PersonaPreset[]> | null>(null);
  const [initial, setInitial] = useState<PersonaSettings | null>(null);
  const [drafts, setDrafts] = useState<PersonaDrafts>(emptyDrafts);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    configApi
      .getPersona()
      .then((view) => {
        if (cancelled) return;
        setPresets(view.presets);
        setInitial(view.current);
        setDrafts({
          soul: draftFromSettings(view.current.soulPreset, view.current.soulCustom),
          personality: draftFromSettings(
            view.current.personalityPreset,
            view.current.personalityCustom,
          ),
          style: draftFromSettings(view.current.stylePreset, view.current.styleCustom),
        });
      })
      .catch(() => {
        if (!cancelled) setError(t("persona.errorLoad"));
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const updateDimension = useCallback((dim: PersonaDimension, next: DimensionDraft) => {
    setDrafts((prev) => ({ ...prev, [dim]: next }));
    setFeedback(null);
  }, []);

  async function handleSave() {
    if (!initial) return;
    setBusy(true);
    setError(null);
    try {
      const payload = buildPersonaPayload(drafts);
      const saved = await configApi.putPersona(payload);
      setInitial(saved);
      setFeedback(t("persona.saved"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("persona.errorSave"));
    } finally {
      setBusy(false);
    }
  }

  async function handleReset() {
    setBusy(true);
    setError(null);
    try {
      const saved = await configApi.putPersona(buildPersonaPayload(emptyDrafts()));
      setInitial(saved);
      setDrafts(emptyDrafts());
      setFeedback(t("persona.resetDone"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("persona.errorSave"));
    } finally {
      setBusy(false);
    }
  }

  if (error && !initial) {
    return <p className="settings__error">{error}</p>;
  }
  if (!presets || !initial) {
    return <p className="settings__item-sub">{t("status.connecting")}</p>;
  }

  const dirty = personaDirty(initial, drafts);

  const dimMeta: Record<PersonaDimension, { title: string; desc: string }> = {
    soul: { title: t("persona.soul"), desc: t("persona.soulDesc") },
    personality: { title: t("persona.personality"), desc: t("persona.personalityDesc") },
    style: { title: t("persona.style"), desc: t("persona.styleDesc") },
  };

  return (
    <>
      <p className="persona__intro">{t("persona.intro")}</p>

      {DIMENSIONS.map((dim) => {
        const draft = drafts[dim];
        return (
          <section key={dim} className="persona__dim">
            <h3 className="settings__section">
              {dimMeta[dim].title}
              <span className="persona__dim-desc">{dimMeta[dim].desc}</span>
            </h3>
            <div className="persona__cards">
              {presets[dim].map((preset) => {
                const selected = !draft.customSelected && draft.presetId === preset.id;
                return (
                  <button
                    key={preset.id}
                    type="button"
                    className={`persona__card${selected ? " persona__card--selected" : ""}`}
                    aria-pressed={selected}
                    onClick={() => updateDimension(dim, selectPreset(draft, preset.id))}
                  >
                    <span className="persona__card-name">
                      {presetLabel(preset, locale, "name")}
                    </span>
                    <span className="persona__card-desc">
                      {presetLabel(preset, locale, "description")}
                    </span>
                  </button>
                );
              })}
              <button
                type="button"
                className={`persona__card${draft.customSelected ? " persona__card--selected" : ""}`}
                aria-pressed={draft.customSelected}
                onClick={() => updateDimension(dim, selectCustom(draft))}
              >
                <span className="persona__card-name">{t("persona.custom")}</span>
                <span className="persona__card-desc">{t("persona.customDesc")}</span>
              </button>
            </div>
            {draft.customSelected ? (
              <textarea
                className="persona__textarea"
                value={draft.customText}
                maxLength={PERSONA_CUSTOM_MAX}
                placeholder={t("persona.customPlaceholder")}
                aria-label={t("persona.custom")}
                onChange={(e) => updateDimension(dim, { ...draft, customText: e.target.value })}
              />
            ) : null}
          </section>
        );
      })}

      {feedback ? <p className="settings__feedback">{feedback}</p> : null}
      {error && initial ? <p className="settings__error">{error}</p> : null}

      <div className="persona__actions">
        <button className="btn" disabled={!dirty || busy} onClick={() => void handleSave()}>
          {t("persona.save")}
        </button>
        <button className="btn btn--ghost" disabled={busy} onClick={() => void handleReset()}>
          {t("persona.resetDefault")}
        </button>
      </div>
    </>
  );
}
