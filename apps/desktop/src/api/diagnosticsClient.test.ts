import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { exportSettings, importSettings } from "./diagnosticsClient";

const mocks = vi.hoisted(() => ({
  invoke: vi.fn(),
  native: vi.fn(),
  save: vi.fn(),
  open: vi.fn(),
  emit: vi.fn(),
}));
vi.mock("@tauri-apps/api/core", () => ({ invoke: mocks.invoke, isTauri: mocks.native }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ save: mocks.save, open: mocks.open }));
vi.mock("@tauri-apps/api/event", () => ({ emit: mocks.emit }));

const backup = {
  format: "mochi-settings",
  version: 1,
  exportedAt: "2026-10-10T00:00:00Z",
  general: { language: "zh-CN", powerSave: true },
  character: { activeSkin: "mochi-vrm" },
  voice: { ttsEnabled: false, volume: 0.3 },
  persona: { styleCustom: "温柔" },
};
const applied = { general: backup.general, character: backup.character, voice: backup.voice };
let saved = "";

beforeEach(() => {
  vi.clearAllMocks();
  mocks.native.mockReturnValue(true);
  mocks.save.mockResolvedValue("/tmp/mochi-settings.json");
  mocks.open.mockResolvedValue("/tmp/mochi-settings.json");
  mocks.emit.mockResolvedValue(undefined);
  mocks.invoke.mockImplementation(async (command, args) => {
    if (command === "write_text_file") saved = args.contents;
    if (command === "read_text_file") return saved;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (url) =>
        new Response(JSON.stringify(String(url).endsWith("/config/export") ? backup : applied)),
    ),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("settings files", () => {
  it("exports UTF-8 JSON and imports the complete backup in one transaction", async () => {
    const bytes = await exportSettings();
    expect(bytes).toBe(new TextEncoder().encode(saved).length);
    expect(JSON.parse(saved)).toEqual(backup);
    expect(await importSettings()).toBe(true);
    const fetchMock = vi.mocked(fetch);
    expect(fetchMock).toHaveBeenLastCalledWith(
      "http://127.0.0.1:8199/config/import",
      expect.objectContaining({ method: "POST", body: JSON.stringify(backup) }),
    );
    expect(mocks.emit).toHaveBeenCalledWith("mochi:skin-changed", "mochi-vrm");
    expect(mocks.emit).toHaveBeenCalledWith("mochi:power-save-changed", { powerSave: true });
  });

  it("cancelled save and open dialogs neither write nor import", async () => {
    mocks.save.mockResolvedValue(null);
    mocks.open.mockResolvedValue(null);
    expect(await exportSettings()).toBeNull();
    expect(await importSettings()).toBeNull();
    expect(mocks.invoke).not.toHaveBeenCalled();
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  });

  it.each(["not JSON", "null", "[]", '"string"'])(
    "rejects %s before changing settings",
    async (raw) => {
      saved = raw;
      await expect(importSettings()).rejects.toThrow("invalid-json");
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it("accepts a browser-selected UTF-8 file with BOM without invoking native dialogs", async () => {
    mocks.native.mockReturnValue(false);
    const file = new File(["\uFEFF" + JSON.stringify(backup)], "settings.json");
    expect(await importSettings(file)).toBe(true);
    expect(mocks.open).not.toHaveBeenCalled();
    expect(mocks.invoke).not.toHaveBeenCalled();
    expect(mocks.emit).not.toHaveBeenCalled();
  });

  it("refuses oversized settings before reading them", async () => {
    const file = new File(["x".repeat(2 * 1024 * 1024 + 1)], "settings.json");
    await expect(importSettings(file)).rejects.toThrow("settings-file-too-large");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("propagates server rejection rather than claiming an import succeeded", async () => {
    saved = JSON.stringify({ character: { activeSkin: "missing" } });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ detail: "请先导入角色" }), { status: 422 }),
        ),
    );
    await expect(importSettings()).rejects.toThrow("请先导入角色");
    expect(mocks.emit).not.toHaveBeenCalled();
  });

  it("downloads a browser backup and releases its object URL", async () => {
    mocks.native.mockReturnValue(false);
    vi.useFakeTimers();
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const link = { href: "", download: "", click: vi.fn(), remove: vi.fn() };
    vi.stubGlobal("document", { createElement: () => link, body: { appendChild: vi.fn() } });
    await exportSettings();
    expect(create).toHaveBeenCalledWith(expect.any(Blob));
    expect(link.download).toBe("mochi-settings.json");
    expect(link.click).toHaveBeenCalledOnce();
    expect(mocks.save).not.toHaveBeenCalled();
    await vi.runAllTimersAsync();
    expect(revoke).toHaveBeenCalledWith("blob:test");
    vi.useRealTimers();
  });
});
