/** 语音输入纯函数与常量测试（node 环境直测，仓库惯例）。 */
import { describe, expect, it } from "vitest";
import { MAX_RECORD_MS, micErrorKey } from "./useVoiceInput";

describe("micErrorKey", () => {
  it("权限拒绝 → 引导系统设置", () => {
    const denied = new DOMException("denied", "NotAllowedError");
    expect(micErrorKey(denied)).toBe("chat.micPermissionDenied");
  });
  it("其他失败（含非 DOM 异常）→ 转写失败", () => {
    expect(micErrorKey(new DOMException("abort", "AbortError"))).toBe("chat.asrFailed");
    expect(micErrorKey(new Error("network"))).toBe("chat.asrFailed");
  });
});

describe("MAX_RECORD_MS", () => {
  it("60s 上限（16kHz mono PCM16 ≈ 1.9MB，远低于服务端 20MB）", () => {
    expect(MAX_RECORD_MS).toBe(60_000);
  });
});
