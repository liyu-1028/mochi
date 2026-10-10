import { beforeEach, expect, it, vi } from "vitest";
import { useAppUpdates } from "./appUpdates";
const mocks = vi.hoisted(() => ({ current: vi.fn(), latest: vi.fn() }));
vi.mock("../api/appUpdates", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/appUpdates")>()),
  getCurrentVersion: mocks.current,
  getLatestRelease: mocks.latest,
}));
beforeEach(() => {
  vi.clearAllMocks();
  useAppUpdates.setState({ currentVersion: null, release: null, status: "idle", checkedAt: null });
  mocks.current.mockResolvedValue("0.15.0");
  mocks.latest.mockResolvedValue({
    version: "0.16.0",
    url: "https://github.com/liyu-1028/mochi/releases/tag/v0.16.0",
  });
});
it("automatically detects an upgrade and caches repeated checks", async () => {
  await useAppUpdates.getState().check();
  expect(useAppUpdates.getState().status).toBe("available");
  expect(useAppUpdates.getState().release?.version).toBe("0.16.0");
  await useAppUpdates.getState().check();
  expect(mocks.latest).toHaveBeenCalledOnce();
  await useAppUpdates.getState().check(true);
  expect(mocks.latest).toHaveBeenCalledTimes(2);
});
it("deduplicates simultaneous checks", async () => {
  await Promise.all([useAppUpdates.getState().check(), useAppUpdates.getState().check()]);
  expect(mocks.latest).toHaveBeenCalledOnce();
});
it("does not offer a downgrade", async () => {
  mocks.current.mockResolvedValue("0.17.0");
  await useAppUpdates.getState().check();
  expect(useAppUpdates.getState().status).toBe("current");
  expect(useAppUpdates.getState().release).toBeNull();
});
it("keeps the current version and retry action on network failure", async () => {
  mocks.latest.mockRejectedValue(new Error("network unavailable"));
  await useAppUpdates.getState().check();
  expect(useAppUpdates.getState().currentVersion).toBe("0.15.0");
  expect(useAppUpdates.getState().status).toBe("error");
  expect(useAppUpdates.getState().release).toBeNull();
});
