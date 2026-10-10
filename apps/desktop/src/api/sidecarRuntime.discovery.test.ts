import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ invoke: vi.fn(), listen: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: mocks.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: mocks.listen }));

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.stubGlobal("window", { __TAURI_INTERNALS__: {} });
  vi.stubEnv("VITE_API_URL", "");
  mocks.listen.mockResolvedValue(() => undefined);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("independent webview sidecar discovery", () => {
  it("loads wardrobe from the actual port when the ready event occurred before the panel opened", async () => {
    mocks.invoke.mockResolvedValue(56873);
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "http://127.0.0.1:56873/skins") {
        return new Response(JSON.stringify([{ id: "mochi-vrm", source: "builtin" }]));
      }
      if (url === "http://127.0.0.1:56873/config/character") {
        return new Response(JSON.stringify({ activeSkin: "mochi-vrm" }));
      }
      throw new TypeError("Failed to fetch");
    });
    vi.stubGlobal("fetch", fetchMock);
    const { initRuntimePortListener } = await import("./sidecarRuntime");
    const { skinsApi } = await import("./skinsClient");
    const { configApi } = await import("./configClient");
    await initRuntimePortListener();
    const [skins, character] = await Promise.all([skinsApi.listSkins(), configApi.getCharacter()]);
    expect(skins[0].id).toBe("mochi-vrm");
    expect(character.activeSkin).toBe("mochi-vrm");
    expect(mocks.invoke).toHaveBeenCalledWith("get_sidecar_port");
    expect(mocks.listen.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.invoke.mock.invocationCallOrder[0],
    );
  });

  it("waits for cold-start discovery before making the panel's first request", async () => {
    let discover!: (port: number) => void;
    mocks.invoke.mockReturnValue(
      new Promise<number>((resolve) => {
        discover = resolve;
      }),
    );
    const fetchMock = vi.fn().mockResolvedValue(new Response("[]"));
    vi.stubGlobal("fetch", fetchMock);
    const { initRuntimePortListener } = await import("./sidecarRuntime");
    const { skinsApi } = await import("./skinsClient");
    const startup = Promise.resolve(initRuntimePortListener()).then(() => skinsApi.listSkins());
    await vi.waitFor(() => expect(mocks.invoke).toHaveBeenCalledOnce());
    expect(fetchMock).not.toHaveBeenCalled();
    discover(56873);
    await startup;
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:56873/skins");
  });

  it("initializes once and preserves newer events received during the snapshot query", async () => {
    let discover!: (port: number) => void;
    mocks.invoke.mockReturnValue(
      new Promise<number>((resolve) => {
        discover = resolve;
      }),
    );
    const { initRuntimePortListener, getRuntimePort, subscribeRuntimePort } =
      await import("./sidecarRuntime");
    const changed = vi.fn();
    const unsubscribe = subscribeRuntimePort(changed);
    const startup = initRuntimePortListener();
    expect(initRuntimePortListener()).toBe(startup);
    await vi.waitFor(() => expect(mocks.invoke).toHaveBeenCalledOnce());
    const ready = mocks.listen.mock.calls[0][1];
    ready({ payload: { port: 65536 } });
    expect(getRuntimePort()).toBeNull();
    ready({ payload: { port: 56875 } });
    discover(56873);
    await startup;
    expect(getRuntimePort()).toBe(56875);
    ready({ payload: { port: 56875 } });
    expect(changed).toHaveBeenCalledTimes(1);
    unsubscribe();
    ready({ payload: { port: 56876 } });
    expect(getRuntimePort()).toBe(56876);
    expect(changed).toHaveBeenCalledTimes(1);
  });

  it("keeps browser development independent of Tauri", async () => {
    vi.stubGlobal("window", {});
    const { initRuntimePortListener, getRuntimePort } = await import("./sidecarRuntime");
    await initRuntimePortListener();
    expect(getRuntimePort()).toBeNull();
    expect(mocks.listen).not.toHaveBeenCalled();
    expect(mocks.invoke).not.toHaveBeenCalled();
  });
});
