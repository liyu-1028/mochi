import { create } from "zustand";
import {
  getCurrentVersion,
  getLatestRelease,
  isNewerVersion,
  type AppRelease,
} from "../api/appUpdates";

type CheckStatus = "idle" | "checking" | "current" | "available" | "error";
interface AppUpdatesState {
  currentVersion: string | null;
  release: AppRelease | null;
  status: CheckStatus;
  checkedAt: number | null;
  check: (force?: boolean) => Promise<void>;
}

let pending: Promise<void> | null = null;
export const useAppUpdates = create<AppUpdatesState>()((set, get) => ({
  currentVersion: null,
  release: null,
  status: "idle",
  checkedAt: null,
  check: (force = false) => {
    if (pending) return pending;
    const state = get();
    const retryAfter = state.status === "error" ? 5 * 60_000 : 60 * 60_000;
    if (!force && state.checkedAt !== null && Date.now() - state.checkedAt < retryAfter) {
      return Promise.resolve();
    }
    set({ status: "checking" });
    pending = (async () => {
      try {
        const currentVersion = state.currentVersion ?? (await getCurrentVersion());
        set({ currentVersion });
        const latest = await getLatestRelease(force);
        const release = latest && isNewerVersion(latest.version, currentVersion) ? latest : null;
        set({ release, status: release ? "available" : "current", checkedAt: Date.now() });
      } catch {
        set({ status: "error", checkedAt: Date.now() });
      } finally {
        pending = null;
      }
    })();
    return pending;
  },
}));
