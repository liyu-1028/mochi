/**
 * SkinsPanel —— Mochi 的衣橱（M1-CTX 预告式面板）。
 *
 * 皮肤系统整体属 M1-S3（SkinRegistry/切换未实现）；本面板先立住入口：
 * 展示当前皮肤（Hiyori）的清单信息（运行时读 /skins/hiyori/skin.json，
 * 失败降级内置常量）+ 「更多皮肤制作中」预告 + 禁用态换装按钮。
 * active_skin 配置不动；S3 时此面板接 SkinRegistry。
 */
import { useEffect, useState } from "react";
import { useI18n } from "../i18n";

interface SkinsPanelProps {
  onClose: () => void;
}

interface SkinManifest {
  id: string;
  name: string;
  resourceType: string;
  license: string;
  credits?: { illustration?: string; model?: string };
}

/** fetch 失败（release 路径差异等）时的兜底信息，与 skin.json 保持一致。 */
const FALLBACK_SKIN: SkinManifest = {
  id: "hiyori",
  name: "Hiyori（桃瀬ひより）",
  resourceType: "live2d",
  license: "Live2D Free Material License Agreement + Terms of Use for Live2D Cubism Sample Data",
  credits: { illustration: "Kani Biimu", model: "Live2D Inc." },
};

const SKIN_MANIFEST_URL = "/skins/hiyori/skin.json";

export function SkinsPanel({ onClose }: SkinsPanelProps) {
  const { t } = useI18n();
  const [skin, setSkin] = useState<SkinManifest>(FALLBACK_SKIN);

  useEffect(() => {
    let cancelled = false;
    fetch(SKIN_MANIFEST_URL)
      .then((resp) => (resp.ok ? resp.json() : Promise.reject(new Error("bad status"))))
      .then((data: SkinManifest) => {
        if (!cancelled) setSkin(data);
      })
      .catch(() => {
        /* 保留 FALLBACK_SKIN */
      });
    return () => {
      cancelled = true;
    };
  }, []);

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

        <div className="settings__item">
          <div className="settings__item-main">
            <strong>{skin.name}</strong>
            <span className="settings__item-sub">
              {t("skins.current")} · {skin.resourceType}
            </span>
          </div>
          <span className="settings__tag">{t("settings.inUse")}</span>
        </div>

        <dl className="skins__credits">
          {skin.credits?.illustration ? (
            <>
              <dt>{t("skins.creditIllustration")}</dt>
              <dd>{skin.credits.illustration}</dd>
            </>
          ) : null}
          {skin.credits?.model ? (
            <>
              <dt>{t("skins.creditModel")}</dt>
              <dd>{skin.credits.model}</dd>
            </>
          ) : null}
          <dt>{t("skins.license")}</dt>
          <dd className="skins__license">{skin.license}</dd>
        </dl>

        <p className="settings__feedback skins__soon">{t("skins.comingSoon")}</p>

        <button className="btn" disabled title={t("skins.switchDisabled")}>
          {t("skins.switchDisabled")}
        </button>
      </div>
    </div>
  );
}
