/**
 * configClient 测试：fetch 封装的请求构造与错误处理（mock fetch）。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { configApi, resolveHttpBaseUrl } from "./configClient";

function mockFetch(body: unknown, status = 200) {
  const fn = vi.fn().mockResolvedValue({
    ok: status < 400,
    status,
    statusText: `HTTP ${status}`,
    json: async () => body,
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("resolveHttpBaseUrl", () => {
  it("默认指向本地 sidecar 8199", () => {
    expect(resolveHttpBaseUrl()).toBe("http://127.0.0.1:8199");
  });
});

describe("configApi", () => {
  it("listProviders GET /config/providers", async () => {
    const fetchMock = mockFetch([{ id: "cloud", isDefault: true }]);
    const list = await configApi.listProviders();
    expect(list).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8199/config/providers",
      expect.objectContaining({ headers: { "Content-Type": "application/json" } }),
    );
  });

  it("createProvider POST 携带 JSON body", async () => {
    const fetchMock = mockFetch({ id: "deepseek" }, 201);
    await configApi.createProvider({
      id: "deepseek",
      kind: "openai_compatible",
      displayName: "DeepSeek",
      model: "deepseek-chat",
      apiKey: "sk-x",
    });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toMatchObject({ id: "deepseek", apiKey: "sk-x" });
  });

  it("updateProvider PUT /config/providers/{id} 携带部分字段", async () => {
    const fetchMock = mockFetch({ id: "deepseek", model: "deepseek-chat" });
    const resp = await configApi.updateProvider("deepseek", {
      model: "deepseek-chat",
      apiKey: "sk-new",
    });
    expect(resp.model).toBe("deepseek-chat");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8199/config/providers/deepseek");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toMatchObject({ model: "deepseek-chat", apiKey: "sk-new" });
  });

  it("updateProvider 未传字段不出现在请求体（部分更新语义）", async () => {
    const fetchMock = mockFetch({ id: "cloud" });
    await configApi.updateProvider("cloud", { displayName: "云端" });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body).toEqual({ displayName: "云端" });
  });

  it("setDefault PUT /config/providers/{id}/default", async () => {
    const fetchMock = mockFetch({ defaultProvider: "ollama" });
    const resp = await configApi.setDefault("ollama");
    expect(resp.defaultProvider).toBe("ollama");
    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://127.0.0.1:8199/config/providers/ollama/default",
    );
  });

  it("deleteProvider 204 → undefined", async () => {
    mockFetch(undefined, 204);
    await expect(configApi.deleteProvider("cloud")).resolves.toBeUndefined();
  });

  it("错误响应抛出服务端 detail 文案", async () => {
    mockFetch({ detail: "提供方 cloud 已存在" }, 409);
    await expect(
      configApi.createProvider({
        id: "cloud",
        kind: "ollama",
        displayName: "x",
        model: "m",
      }),
    ).rejects.toThrow("提供方 cloud 已存在");
  });

  it("ollamaStatus 返回探测结果", async () => {
    mockFetch({ available: true, models: ["qwen3:8b"] });
    const status = await configApi.ollamaStatus();
    expect(status.available).toBe(true);
    expect(status.models).toEqual(["qwen3:8b"]);
  });

  it("getCharacter GET /config/character", async () => {
    const fetchMock = mockFetch({ activeSkin: "default" });
    const view = await configApi.getCharacter();
    expect(view.activeSkin).toBe("default");
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:8199/config/character");
  });

  it("setCharacter PUT /config/character 携带 activeSkin", async () => {
    const fetchMock = mockFetch({ activeSkin: "mochi-julia" });
    await configApi.setCharacter({ activeSkin: "mochi-julia" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8199/config/character");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ activeSkin: "mochi-julia" });
  });

  it("getPersona GET /config/persona 返回 current + presets", async () => {
    const fetchMock = mockFetch({ current: { soulPreset: "warm_sun" }, presets: {} });
    const view = await configApi.getPersona();
    expect(view.current.soulPreset).toBe("warm_sun");
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:8199/config/persona");
  });

  it("putPersona PUT /config/persona 携带全量 persona", async () => {
    const fetchMock = mockFetch({ soulPreset: "warm_sun" });
    await configApi.putPersona({
      soulPreset: "warm_sun",
      soulCustom: "",
      personalityPreset: "",
      personalityCustom: "",
      stylePreset: "",
      styleCustom: "说话像海盗",
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8199/config/persona");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toMatchObject({
      soulPreset: "warm_sun",
      styleCustom: "说话像海盗",
    });
  });
});
