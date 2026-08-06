/**
 * SkinsPanel —— Mochi 的衣橱（M1-S1，功能清单 3.2/3.3/3.4/3.5）。
 *
 * 列表（内置 + 用户）→ 一键激活（PUT /config/character 落盘持久化）→
 * 跨窗口经 EVENT_SKIN_CHANGED 通知主窗口重建舞台；浏览器内联降级同窗口
 * 经 onSkinActivated 回调。导入 PNG/zip（服务端校验，错误可读）；
 * 用户皮肤可删（confirm 二次确认）。致谢区跟随当前皮肤。
 */
import { useEffect, useState, type ChangeEvent } from "react";
import { emit } from "@tauri-apps/api/event";
import { configApi } from "../api/configClient";
import { resolveSkinId, skinsApi, type SkinSummary } from "../api/skinsClient";
import { useI18n } from "../i18n";
import { EVENT_SKIN_CHANGED } from "../panelWindow";

interface SkinsPanelProps {
  onClose: () => void;
  /** 浏览器内联降级（同窗口）换肤后回调 App 刷新；桌面端走 Tauri 事件。 */
  onSkinActivated?: (skinId: string) => void;
}

const IS_TAURI = "__TAURI_INTERNALS__" in window;

export function SkinsPanel({ onClose, onSkinActivated }: SkinsPanelProps) {
  const { t } = useI18n();
  const [skins, setSkins] = useState<SkinSummary[]>([]);
  const [activeSkinId, setActiveSkinId] = useState("default");
  const [switching, setSwitching] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 删除两步确认（内联，与 HistoryPanel 同模式；Tauri webview 不依赖 JS 对话框）
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([skinsApi.listSkins(), configApi.getCharacter()])
      .then(([list, character]) => {
        if (cancelled) return;
        setSkins(list);
        setActiveSkinId(character.activeSkin);
      })
      .catch(() => {
        if (!cancelled) setError(t("skins.errorLoad"));
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const resolvedActive = resolveSkinId(activeSkinId);
  const activeSkin = skins.find((s) => s.id === resolvedActive);

  async function handleActivate(skinId: string) {
    setSwitching(skinId);
    setError(null);
    try {
      await configApi.setCharacter({ activeSkin: skinId });
      setActiveSkinId(skinId);
      onSkinActivated?.(skinId);
      if (IS_TAURI) await emit(EVENT_SKIN_CHANGED, skinId);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("skins.errorSave"));
    } finally {
      setSwitching(null);
    }
  }

  async function handleImport(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // 允许重新选同一文件
    if (!file) return;
    setImporting(true);
    setError(null);
    try {
      const created = await skinsApi.importSkin(file);
      setSkins((prev) => [...prev, created]);
      await handleActivate(created.id); // 导入即穿上（3.4 ≤1 分钟可用）
    } catch (err) {
      setError(err instanceof Error ? err.message : t("skins.errorSave"));
    } finally {
      setImporting(false);
    }
  }

  async function handleDelete(skinId: string) {
    setConfirmDeleteId(null);
    setError(null);
    try {
      await skinsApi.deleteSkin(skinId);
      setSkins((prev) => prev.filter((s) => s.id !== skinId));
      // 删的正是当前皮肤：服务端已回退 default，前端同步
      if (resolvedActive === skinId) await handleActivate("default");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("skins.errorSave"));
    }
  }

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings" onClick={(e) => e.stopPropagation()}>
        {/* data-tauri-drag-region：无边框面板窗口以头部为拖拽区（button 子元素自动豁免） */}
        <header className="settings__header" data-tauri-drag-region>
          <h2>{t("skins.title")}</h2>
          <button className="settings__close" onClick={onClose} aria-label={t("common.close")}>
            ×
          </button>
        </header>

        <div className="skins__list">
          {skins.map((skin) => {
            const isActive = skin.id === resolvedActive;
            return (
              <div key={skin.id} className="settings__item">
                <div className="settings__item-main">
                  <strong>{skin.name}</strong>
                  <span className="settings__item-sub">
                    {skin.resourceType} ·{" "}
                    {skin.source === "builtin" ? t("skins.builtin") : t("skins.user")}
                  </span>
                </div>
                <div className="settings__item-actions">
                  {isActive ? (
                    <span className="settings__tag">{t("settings.inUse")}</span>
                  ) : (
                    <button
                      className="btn btn--ghost"
                      disabled={switching !== null}
                      onClick={() => void handleActivate(skin.id)}
                    >
                      {switching === skin.id ? t("skins.switching") : t("skins.activate")}
                    </button>
                  )}
                  {skin.source === "user" ? (
                    confirmDeleteId === skin.id ? (
                      <>
                        <button
                          className="btn btn--ghost settings__danger"
                          disabled={switching !== null}
                          onClick={() => void handleDelete(skin.id)}
                        >
                          {t("common.delete")}
                        </button>
                        <button className="btn btn--ghost" onClick={() => setConfirmDeleteId(null)}>
                          {t("common.cancel")}
                        </button>
                      </>
                    ) : (
                      <button
                        className="btn btn--ghost settings__danger"
                        disabled={switching !== null}
                        onClick={() => setConfirmDeleteId(skin.id)}
                        aria-label={t("common.delete")}
                      >
                        🗑
                      </button>
                    )
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>

        {error ? <p className="settings__error">{error}</p> : null}

        {/* 致谢区：跟随当前皮肤 */}
        {activeSkin ? (
          <dl className="skins__credits">
            {activeSkin.credits?.illustration ? (
              <>
                <dt>{t("skins.creditIllustration")}</dt>
                <dd>{activeSkin.credits.illustration}</dd>
              </>
            ) : null}
            {activeSkin.credits?.model ? (
              <>
                <dt>{t("skins.creditModel")}</dt>
                <dd>{activeSkin.credits.model}</dd>
              </>
            ) : null}
            <dt>{t("skins.license")}</dt>
            <dd className="skins__license">{activeSkin.license}</dd>
          </dl>
        ) : null}

        <div className="skins__import">
          <label className="btn">
            {importing ? t("skins.importing") : t("skins.import")}
            <input
              type="file"
              accept=".png,.zip"
              hidden
              disabled={importing}
              onChange={(e) => void handleImport(e)}
            />
          </label>
        </div>
        <p className="skins__hint">{t("skins.transparencyHint")}</p>
      </div>
    </div>
  );
}
