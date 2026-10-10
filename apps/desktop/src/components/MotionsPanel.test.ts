import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MotionsPanel } from "./MotionsPanel";

describe("motion import purpose", () => {
  it("starts with custom purpose rather than silently claiming wave", () => {
    const html = renderToStaticMarkup(createElement(MotionsPanel, { onClose: () => undefined }));
    expect(html).toContain('<option value="" selected="">自定义动作</option>');
    expect(html).not.toContain('<option value="wave" selected="">');
  });
});
