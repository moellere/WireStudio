import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProblemsPanel, type SolveResult } from "./ProblemsPanel";
import type { CompatibilityWarning, Design } from "../types/api";

const design = {
  schema_version: "1.0", id: "d", name: "d",
  board: { library_id: "esp32-devkitc-v4", mcu: "esp32" },
  warnings: [{ level: "warn", code: "w1", text: "check the rail" }],
} as unknown as Design;

const compat: CompatibilityWarning[] = [
  { severity: "error", code: "input_only", pin: "GPIO34", component_id: "led", pin_role: "OUT", message: "GPIO34 is input-only" },
];

function setup(over: Partial<Parameters<typeof ProblemsPanel>[0]> = {}) {
  const props = {
    design, compatibilityWarnings: compat, solve: null as SolveResult | null,
    onDismissSolve: vi.fn(), onDesignChange: vi.fn(), ...over,
  };
  const r = render(<ProblemsPanel {...props} />);
  return { props, ...r };
}

beforeEach(() => window.localStorage.clear());

describe("ProblemsPanel", () => {
  it("counts each kind and opens on the checker's findings", () => {
    setup();
    expect(screen.getByRole("tab", { name: /Compatibility\s*1/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /Warnings\s*1/ })).toBeInTheDocument();
    expect(screen.getByText("[error] input_only")).toBeInTheDocument();
  });

  it("edits the design's own warnings in the Warnings tab", () => {
    const { props } = setup();
    fireEvent.click(screen.getByRole("tab", { name: /Warnings/ }));
    fireEvent.click(screen.getByText("+ Add warning"));
    expect(props.onDesignChange).toHaveBeenCalledOnce();
  });

  it("switches to the Solver tab and expands when a solve lands", () => {
    const { rerender, props } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Collapse problems" }));
    expect(screen.queryByRole("tabpanel")).not.toBeInTheDocument();
    const solve: SolveResult = {
      assigned: [{ component_id: "led", pin_role: "OUT", old_target: {}, new_target: { kind: "gpio", pin: "GPIO4" } }],
      unresolved: [], warnings: [{ level: "warn", code: "boot_strap", text: "GPIO4 is a strap" }],
    };
    rerender(<ProblemsPanel {...props} solve={solve} />);
    expect(screen.getByRole("tab", { name: /Solver\s*1/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getAllByText(/Solver assigned 1 pin · 1 issue/).length).toBeGreaterThan(0);
  });

  it("remembers being collapsed", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Collapse problems" }));
    expect(window.localStorage.getItem("wirestudio:ui:problems-collapsed")).toBe("1");
  });
});
