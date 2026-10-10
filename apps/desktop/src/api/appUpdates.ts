/** GitHub's public stable releases; no credentials or user configuration are transmitted. */
import { getVersion } from "@tauri-apps/api/app";
import { isTauri } from "@tauri-apps/api/core";
import tauriConfig from "../../src-tauri/tauri.conf.json";
import { resolveHttpBaseUrl } from "./configClient";

export const RELEASES_URL = "https://github.com/liyu-1028/mochi/releases";

export interface AppRelease {
  version: string;
  url: string;
}

function parseVersion(version: string) {
  const match =
    /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/.exec(
      version,
    );
  if (!match) throw new Error("Invalid release version");
  const core = match.slice(1, 4).map(Number);
  if (!core.every(Number.isSafeInteger)) throw new Error("Invalid release version");
  const pre = match[4]?.split(".") ?? [];
  if (
    pre.some((part) => !part || (/^\d+$/.test(part) && part.length > 1 && part.startsWith("0")))
  ) {
    throw new Error("Invalid release version");
  }
  return { core, pre };
}

/** SemVer order, including numeric prerelease identifiers; build metadata does not affect order. */
export function isNewerVersion(candidate: string, current: string): boolean {
  const a = parseVersion(candidate);
  const b = parseVersion(current);
  for (let i = 0; i < 3; i++) {
    if (a.core[i] !== b.core[i]) return a.core[i] > b.core[i];
  }
  if (!a.pre.length || !b.pre.length) return !a.pre.length && b.pre.length > 0;
  for (let i = 0; i < Math.max(a.pre.length, b.pre.length); i++) {
    const x = a.pre[i];
    const y = b.pre[i];
    if (x === y) continue;
    if (x === undefined || y === undefined) return y === undefined;
    const xn = /^\d+$/.test(x);
    const yn = /^\d+$/.test(y);
    if (xn && yn) return x.length !== y.length ? x.length > y.length : x > y;
    if (xn !== yn) return !xn;
    return x > y;
  }
  return false;
}

export async function getCurrentVersion(): Promise<string> {
  return isTauri() ? getVersion() : tauriConfig.version;
}

export async function getLatestRelease(force = false): Promise<AppRelease | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(
      `${resolveHttpBaseUrl()}/updates/latest${force ? "?force=true" : ""}`,
      {
        signal: controller.signal,
      },
    );
    if (!response.ok) throw new Error(`Update check HTTP ${response.status}`);
    const release = await response.json();
    if (release === null) return null;
    if (typeof release.version !== "string" || typeof release.url !== "string") {
      throw new Error("Invalid GitHub release");
    }
    const parsed = parseVersion(release.version);
    if (parsed.pre.length) throw new Error("Invalid stable release");
    const tag = release.url.slice(`${RELEASES_URL}/tag/`.length);
    if (
      !release.url.startsWith(`${RELEASES_URL}/tag/`) ||
      tag.replace(/^v/, "") !== release.version
    ) {
      throw new Error("Invalid release URL");
    }
    return { version: release.version, url: release.url };
  } finally {
    clearTimeout(timer);
  }
}
