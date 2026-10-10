import { describe, expect, it } from "vitest";
import { pickImportedIdleMotion } from "./motions";

describe("imported idle pool", () => {
  it("has no built-in fallback when no idle files have been imported", () => {
    expect(pickImportedIdleMotion([], 0)).toBeNull();
    expect(
      pickImportedIdleMotion([{ id: "wave", kind: "oneshot", tags: ["greeting"] }], 0),
    ).toBeNull();
  });
  it("plays only opted-in imported one-shots and leaves quiet time", () => {
    const first = { id: "ext.user.first", kind: "oneshot" as const, tags: ["idle"] };
    const second = { id: "ext.user.second", kind: "oneshot" as const, tags: ["idle"] };
    const library = [
      { id: "idle_neutral", kind: "loop" as const, tags: ["idle"] },
      { id: "wave", kind: "oneshot" as const, tags: [] },
      first,
      second,
    ];
    expect(pickImportedIdleMotion(library, 0)).toBe(first);
    expect(pickImportedIdleMotion(library, 0.2)).toBe(second);
    expect(pickImportedIdleMotion(library, 0.3)).toBeNull();
    expect(pickImportedIdleMotion(library, 0.99)).toBeNull();
  });
});
