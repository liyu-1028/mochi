import { afterEach, describe, expect, it, vi } from "vitest";
import { getCurrentVersion, getLatestRelease, isNewerVersion } from "./appUpdates";
import tauriConfig from "../../src-tauri/tauri.conf.json";
const mocks = vi.hoisted(() => ({ native: vi.fn(() => false), version: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ isTauri: mocks.native }));
vi.mock("@tauri-apps/api/app", () => ({ getVersion: mocks.version }));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  mocks.native.mockReturnValue(false);
});

it.each([
  ["v0.16.0", "0.15.0", true],
  ["0.10.0", "0.9.0", true],
  ["0.15.0", "0.15.0", false],
  ["0.14.9", "0.15.0", false],
  ["0.15.0", "0.15.0-rc.1", true],
  ["0.15.0-beta.2", "0.15.0", false],
  ["0.15.0-rc.10", "0.15.0-rc.2", true],
  ["0.15.0+new", "0.15.0+old", false],
])("compares %s against %s", (candidate, current, expected) => {
  expect(isNewerVersion(candidate, current)).toBe(expected);
});

it("uses the installed app version in Tauri", async () => {
  mocks.native.mockReturnValue(true);
  mocks.version.mockResolvedValue("0.14.0");
  expect(await getCurrentVersion()).toBe("0.14.0");
});
it("uses the Tauri build version in web previews", async () => {
  expect(await getCurrentVersion()).toBe(tauriConfig.version);
});

describe("GitHub releases", () => {
  const release = {
    version: "0.16.0",
    url: "https://github.com/liyu-1028/mochi/releases/tag/v0.16.0",
  };
  it("checks through the local release service with an abort signal", async () => {
    const fn = vi.fn().mockResolvedValue(new Response(JSON.stringify(release)));
    vi.stubGlobal("fetch", fn);
    expect(await getLatestRelease()).toEqual(release);
    expect(fn).toHaveBeenCalledWith(
      "http://127.0.0.1:8199/updates/latest",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });
  it("lets manual checks refresh the shared cache", async () => {
    const fn = vi.fn().mockResolvedValue(new Response(JSON.stringify(release)));
    vi.stubGlobal("fetch", fn);
    await getLatestRelease(true);
    expect(fn.mock.calls[0][0]).toBe("http://127.0.0.1:8199/updates/latest?force=true");
  });
  it.each([
    { version: "0.16.0-rc.1", url: release.url },
    { version: "0.16.0", url: "https://untrusted.example/download" },
    { version: "0.16.0", url: "https://github.com/other/repo/releases/tag/v0.16.0" },
    { version: "0.16.0", url: release.url + "?extra=1" },
  ])("rejects unsafe or prerelease data: %j", async (data) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(data))));
    await expect(getLatestRelease()).rejects.toThrow();
  });
  it("handles repositories without releases", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("null")));
    expect(await getLatestRelease()).toBeNull();
  });
  it("reports network errors instead of falsely claiming the app is current", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 503 })));
    await expect(getLatestRelease()).rejects.toThrow("Update check HTTP 503");
  });
  it("aborts a stalled update check", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url, { signal }) =>
          new Promise((_resolve, reject) => {
            signal.addEventListener("abort", () => reject(new Error("timeout")));
          }),
      ),
    );
    const assertion = expect(getLatestRelease()).rejects.toThrow("timeout");
    await vi.advanceTimersByTimeAsync(8000);
    await assertion;
  });
});
