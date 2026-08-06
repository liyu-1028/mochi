/**
 * skinsClient 测试：请求构造与 default 解析（mock fetch，仓库惯例）。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveSkinId, skinsApi } from "./skinsClient";

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

describe("resolveSkinId", () => {
  it("default 解析为内置默认皮肤，其余原样", () => {
    expect(resolveSkinId("default")).toBe("hiyori");
    expect(resolveSkinId("my-skin")).toBe("my-skin");
  });
});

describe("skinsApi", () => {
  it("listSkins GET /skins", async () => {
    const fetchMock = mockFetch([{ id: "hiyori", source: "builtin" }]);
    const list = await skinsApi.listSkins();
    expect(list).toHaveLength(1);
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:8199/skins");
  });

  it("importSkin 走 FormData 且不设 Content-Type", async () => {
    const fetchMock = mockFetch({ id: "png-abc", source: "user" }, 201);
    const file = new File([new Uint8Array([1, 2, 3])], "cat.png", { type: "image/png" });
    const result = await skinsApi.importSkin(file, "我的猫");
    expect(result.id).toBe("png-abc");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8199/skins/import");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.headers).toBeUndefined(); // 浏览器自动定 multipart boundary
    expect((init.body as FormData).get("file")).toBe(file);
    expect((init.body as FormData).get("skin_name")).toBe("我的猫");
  });

  it("deleteSkin DELETE 带编码", async () => {
    mockFetch(undefined, 204);
    await expect(skinsApi.deleteSkin("a b")).resolves.toBeUndefined();
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("http://127.0.0.1:8199/skins/a%20b");
  });

  it("错误响应抛出服务端 detail", async () => {
    mockFetch({ detail: "皮肤 ID 已存在：dup" }, 409);
    const file = new File([new Uint8Array([1])], "x.png");
    await expect(skinsApi.importSkin(file)).rejects.toThrow("皮肤 ID 已存在：dup");
  });
});
