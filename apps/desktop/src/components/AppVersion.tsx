import { useI18n } from "../i18n";
import { useAppUpdates } from "../store/appUpdates";
import { openExternal } from "../openExternal";

export function AppVersion() {
  const { t } = useI18n();
  const { currentVersion, release, status, check } = useAppUpdates();
  return (
    <footer className="settings__version" aria-label={t("settings.appVersion")}>
      <div className="settings__version-details">
        <strong>Mochi {currentVersion ? `v${currentVersion}` : ""}</strong>
        <small className="settings__hint" role="status">
          {status === "checking"
            ? t("settings.checkingUpdate")
            : status === "error"
              ? t("settings.updateCheckFailed")
              : release
                ? t("settings.updateAvailable", { version: release.version })
                : status === "current"
                  ? t("settings.upToDate")
                  : t("settings.appVersion")}
        </small>
      </div>
      {release ? (
        <button
          type="button"
          className="settings__upgrade"
          title={t("settings.updateAvailable", { version: release.version })}
          aria-label={t("settings.openUpdate", { version: release.version })}
          onClick={() => void openExternal(release.url)}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M12 16V4m-5 5 5-5 5 5M5 16v4h14v-4"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span>{t("settings.upgrade")}</span>
        </button>
      ) : (
        <button
          type="button"
          className="settings__version-check"
          disabled={status === "checking"}
          onClick={() => void check(true)}
        >
          {t("settings.checkUpdate")}
        </button>
      )}
    </footer>
  );
}
