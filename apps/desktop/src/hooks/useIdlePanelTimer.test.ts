import { describe, expect, it } from "vitest";
import { shouldKeepPanelOpen } from "./useIdlePanelTimer";

const baseActivity = {
  isHovered: false,
  isFocused: false,
  hasPendingInput: false,
  hasActiveRun: false,
};

describe("shouldKeepPanelOpen", () => {
  it("all signals false → timer should fire (panel auto-hides)", () => {
    expect(shouldKeepPanelOpen(baseActivity)).toBe(false);
  });

  it("mouse hovering panel → keep open", () => {
    expect(shouldKeepPanelOpen({ ...baseActivity, isHovered: true })).toBe(true);
  });

  it("input focused → keep open", () => {
    expect(shouldKeepPanelOpen({ ...baseActivity, isFocused: true })).toBe(true);
  });

  it("user has unsent draft text → keep open", () => {
    expect(shouldKeepPanelOpen({ ...baseActivity, hasPendingInput: true })).toBe(true);
  });

  it("assistant run active (thinking/tool/streaming) → keep open", () => {
    expect(shouldKeepPanelOpen({ ...baseActivity, hasActiveRun: true })).toBe(true);
  });

  it("any single signal true suffices (multiple true also keep open)", () => {
    expect(
      shouldKeepPanelOpen({
        isHovered: true,
        isFocused: false,
        hasPendingInput: false,
        hasActiveRun: false,
      }),
    ).toBe(true);
    expect(
      shouldKeepPanelOpen({
        isHovered: true,
        isFocused: true,
        hasPendingInput: true,
        hasActiveRun: true,
      }),
    ).toBe(true);
  });
});
