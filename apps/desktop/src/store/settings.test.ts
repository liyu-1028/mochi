/**
 * settings store 测试：语言 hydrate / 乐观切换 / 失败回滚（fetch mock）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_LOCALE } from "../i18n/strings";
import { useSettings } from "./settings";

function mockFetch(impl: (url: string) => Promise<Response>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => impl(String(url))),
  );
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  useSettings.setState({ language: DEFAULT_LOCALE });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("hydrate", () => {
  it("从 sidecar 同步语言设置", async () => {
    mockFetch(() => Promise.resolve(jsonResponse({ general: { language: "en" } })));
    await useSettings.getState().hydrate();
    expect(useSettings.getState().language).toBe("en");
  });

  it("sidecar 未就绪时保持默认语言", async () => {
    mockFetch(() => Promise.reject(new Error("network down")));
    await useSettings.getState().hydrate();
    expect(useSettings.getState().language).toBe(DEFAULT_LOCALE);
  });

  it("非法语言值不覆盖默认", async () => {
    mockFetch(() => Promise.resolve(jsonResponse({ general: { language: "fr" } })));
    await useSettings.getState().hydrate();
    expect(useSettings.getState().language).toBe(DEFAULT_LOCALE);
  });
});

describe("setLanguage", () => {
  it("乐观更新即时生效并持久化", async () => {
    mockFetch(() => Promise.resolve(jsonResponse({ language: "en" })));
    useSettings.getState().setLanguage("en");
    expect(useSettings.getState().language).toBe("en");
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  });

  it("持久化失败时回滚", async () => {
    mockFetch(() => Promise.reject(new Error("boom")));
    useSettings.getState().setLanguage("en");
    expect(useSettings.getState().language).toBe("en");
    await vi.waitFor(() => expect(useSettings.getState().language).toBe(DEFAULT_LOCALE));
  });

  it("相同语言不触发请求", () => {
    mockFetch(() => Promise.resolve(jsonResponse({ language: DEFAULT_LOCALE })));
    useSettings.getState().setLanguage(DEFAULT_LOCALE);
    expect(fetch).not.toHaveBeenCalled();
  });
});
