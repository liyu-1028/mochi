import { describe, expect, it } from "vitest";
import { safeId, uniqueId } from "./ProviderForm";

describe("模型配置自动 ID", () => {
  it("把模型名规整为用户无需填写的安全 ID", () => {
    expect(safeId("Zhipu / GLM-5.3 Flash", "model")).toBe("zhipu-glm-5-3-flash");
  });

  it("纯中文名称回退到稳定 ID", () => {
    expect(safeId("我的模型", "model")).toBe("model");
  });

  it("冲突时自动追加序号", () => {
    const used = new Set(["zhipu-glm", "zhipu-glm-2"]);
    expect(uniqueId("zhipu-glm", used)).toBe("zhipu-glm-3");
  });
});
