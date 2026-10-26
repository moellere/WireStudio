import { beforeEach, describe, expect, it } from "vitest";

import { BOUNDS, clamp, readLayout } from "./layout";

beforeEach(() => window.localStorage.clear());

describe("workbench layout", () => {
  it("clamps every column to its bounds", () => {
    expect(clamp("sidebar", 10)).toBe(BOUNDS.sidebar[0]);
    expect(clamp("inspector", 9999)).toBe(BOUNDS.inspector[1]);
    expect(clamp("agent", 430.6)).toBe(431);
  });

  it("starts from the defaults and leaves the inspector to the window width", () => {
    expect(readLayout()).toEqual({ sidebar: 288, inspector: null, agent: 420, sidebarCollapsed: null });
  });

  it("reads remembered widths back, clamped, and ignores junk", () => {
    window.localStorage.setItem(
      "wirestudio:ui:layout",
      JSON.stringify({ sidebar: 999, inspector: 400, agent: "wide", sidebarCollapsed: true }),
    );
    expect(readLayout()).toEqual({ sidebar: BOUNDS.sidebar[1], inspector: 400, agent: 420, sidebarCollapsed: true });
    window.localStorage.setItem("wirestudio:ui:layout", "{not json");
    expect(readLayout().sidebar).toBe(288);
  });
});
