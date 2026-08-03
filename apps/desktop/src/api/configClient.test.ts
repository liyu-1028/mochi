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
});
