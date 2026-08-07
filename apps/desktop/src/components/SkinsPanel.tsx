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

// typeof 守卫：node 测试环境无 window（core.ts isCubismCoreReady 同惯例）
const IS_TAURI = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

/** 导入归一化长边上限：控磁盘/GPU 纹理（服务端 4096 硬上限仍权威）。 */
export const IMPORT_MAX_EDGE = 2048;
/** max 边低于此值视为小图：软提示不阻断（服务端 64 下限仍硬拒绝）。 */
export const SMALL_IMAGE_EDGE = 256;

export interface PngNormalization {
  downscaleTo: number | null;
  small: boolean;
}

/** 导入尺寸决策纯函数（vitest 直测）：长边超限 → 压缩目标；小图 → 提示。 */
export function decidePngNormalization(w: number, h: number): PngNormalization {
  // 宽高非法（非有限正数，如 0/负/NaN/Infinity）：跳过客户端归一化，
  // 否则下游除零/NaN 污染 canvas 尺寸；原样交服务端硬校验兜底（同读取失败路径）
  if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) {
    return { downscaleTo: null, small: false };
  }
  const longEdge = Math.max(w, h);
  return {
    downscaleTo: longEdge > IMPORT_MAX_EDGE ? IMPORT_MAX_EDGE : null,
    small: longEdge < SMALL_IMAGE_EDGE,
  };
}

/** 读图片自然尺寸；失败（非图片等）返回 null 不阻断，交服务端 magic 校验。 */
function readImageSize(file: File): Promise<{ w: number; h: number } | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve({ w: img.naturalWidth, h: img.naturalHeight });
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      resolve(null);
    };
    img.src = url;
  });
}

/** canvas 降采样长边到 longEdge（高质量平滑，PNG 无损保 alpha）；失败原样返回。 */
async function downscalePng(file: File, longEdge: number): Promise<File> {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error("图片解码失败"));
      el.src = url;
    });
    const scale = longEdge / Math.max(img.naturalWidth, img.naturalHeight);
    const w = Math.round(img.naturalWidth * scale);
    const h = Math.round(img.naturalHeight * scale);
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(img, 0, 0, w, h);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    return blob ? new File([blob], file.name, { type: "image/png" }) : file;
  } catch {
    return file; // 压缩失败原样上传，服务端尺寸上限兜底
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function SkinsPanel({ onClose, onSkinActivated }: SkinsPanelProps) {
  const { t } = useI18n();
  const [skins, setSkins] = useState<SkinSummary[]>([]);
  const [activeSkinId, setActiveSkinId] = useState("default");
  const [switching, setSwitching] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** 导入后的非错误提示（小图分辨率软提示等）。 */
  const [notice, setNotice] = useState<string | null>(null);
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
    const original = e.target.files?.[0];
    e.target.value = ""; // 允许重新选同一文件
    if (!original) return;
    setImporting(true);
    setError(null);
    setNotice(null);
    try {
      // 尺寸归一化：长边超限 canvas 压缩；小图仅软提示（尺寸读取失败不阻断）
      let file = original;
      let small = false;
      const size = await readImageSize(original);
      if (size) {
        const decision = decidePngNormalization(size.w, size.h);
        small = decision.small;
        if (decision.downscaleTo) {
          file = await downscalePng(original, decision.downscaleTo);
        }
      }
      const created = await skinsApi.importSkin(file);
      setSkins((prev) => [...prev, created]);
      if (small) setNotice(t("skins.smallImageHint"));
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
        {notice ? <p className="settings__feedback">{notice}</p> : null}

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
