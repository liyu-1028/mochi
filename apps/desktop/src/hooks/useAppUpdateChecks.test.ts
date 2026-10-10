import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAppUpdateChecks } from "./useAppUpdateChecks";
import { useAppUpdates } from "../store/appUpdates";

const mocks = vi.hoisted(() => ({ effect: vi.fn(), current: vi.fn(), latest: vi.fn() }));
vi.mock("react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react")>()),
  useEffect: mocks.effect,
}));
vi.mock("../api/appUpdates", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/appUpdates")>()),
  getCurrentVersion: mocks.current,
  getLatestRelease: mocks.latest,
}));

let cleanup: (() => void) | undefined;
function mount() {
  useAppUpdateChecks();
  cleanup = mocks.effect.mock.calls[0][0]();
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
  cleanup = undefined;
  vi.stubGlobal("window", new EventTarget());
  useAppUpdates.setState({ currentVersion: null, release: null, status: "idle", checkedAt: null });
  mocks.current.mockResolvedValue("0.15.0");
  mocks.latest.mockResolvedValue(null);
});
afterEach(() => {
  cleanup?.();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("automatically recovers when the sidecar was unavailable at launch", async () => {
  mocks.latest.mockRejectedValueOnce(new Error("sidecar not ready"));
  mount();
  await vi.advanceTimersByTimeAsync(0);
  expect(useAppUpdates.getState().status).toBe("error");
  await vi.advanceTimersByTimeAsync(5 * 60_000);
  expect(mocks.latest).toHaveBeenCalledTimes(2);
  expect(useAppUpdates.getState().status).toBe("current");
});

it("keeps successful checks cached for an hour despite timer and focus events", async () => {
  mount();
  await vi.advanceTimersByTimeAsync(0);
  await vi.advanceTimersByTimeAsync(55 * 60_000);
  window.dispatchEvent(new Event("focus"));
  await vi.advanceTimersByTimeAsync(0);
  expect(mocks.latest).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(5 * 60_000);
  expect(mocks.latest).toHaveBeenCalledTimes(2);
});

it("removes timers and focus listeners when the window unmounts", async () => {
  mount();
  await vi.advanceTimersByTimeAsync(0);
  cleanup?.();
  await vi.advanceTimersByTimeAsync(2 * 60 * 60_000);
  window.dispatchEvent(new Event("focus"));
  await vi.advanceTimersByTimeAsync(0);
  expect(mocks.latest).toHaveBeenCalledOnce();
});
