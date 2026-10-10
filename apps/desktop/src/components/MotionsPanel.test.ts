import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MotionsPanel, motionGroup } from "./MotionsPanel";

describe("motion import purpose", () => {
  it("starts with custom purpose rather than silently claiming wave", () => {
    const html = renderToStaticMarkup(createElement(MotionsPanel, { onClose: () => undefined }));
    expect(html).toContain('<option value="" selected="">自定义动作</option>');
    expect(html).not.toContain('<option value="wave" selected="">');
  });
});

describe("motion grouping", () => {
  it("keeps user-imported role defaults in the built-in group", () => {
    expect(motionGroup({ source: "user", category: "builtin" })).toBe("builtin");
    expect(motionGroup({ source: "builtin" })).toBe("builtin");
    expect(motionGroup({ source: "user", category: "custom" })).toBe("custom");
  });
  it("offers both categories during import", () => {
    const html = renderToStaticMarkup(createElement(MotionsPanel, { onClose: () => undefined }));
    expect(html).toContain('<option value="builtin">角色内置</option>');
    expect(html).toContain('<option value="custom" selected="">用户扩展</option>');
  });
});
