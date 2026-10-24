import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { RouteDrcReport } from "./RouteDrcReport";
import type { DrcSummary } from "../types/api";

const UNROUTED: DrcSummary = {
  kicad_version: "8.0.9", ok: false, unconnected: 2, errors: 0, warnings: 0, waived: 12,
  groups: [
    { type: "unconnected_items", severity: "error", count: 2, waived: false, reason: null, violations: [
      { description: "Missing connection between items", items: [
        { description: "Pad 8 [+3V3] of U2 on F.Cu", pos: { x: 27.47, y: 103.275 } },
        { description: "Pad 2 [+3V3] of M1 on F.Cu", pos: { x: 43.75, y: 52.26 } },
      ] },
      { description: "Missing connection between items", items: [] },
    ] },
    { type: "drill_out_of_range", severity: "error", count: 12, waived: true,
      reason: "module footprints carry vias smaller than KiCad's default minimum hole", violations: [] },
  ],
};

describe("RouteDrcReport", () => {
  it("leads with the unconnected count and lists the items", () => {
    render(<RouteDrcReport drc={UNROUTED} />);
    expect(screen.getByText(/2 unconnected/)).toBeInTheDocument();
    expect(screen.getByText(/Pad 8 \[\+3V3\] of U2 on F\.Cu @ \(27\.47, 103\.28\) mm/)).toBeInTheDocument();
    expect(screen.getByText("waived")).toBeInTheDocument();
  });

  it("says why there is no report", () => {
    const { rerender } = render(<RouteDrcReport drc={null} />);
    expect(screen.getByText(/kicad-cli is not on the server/)).toBeInTheDocument();
    rerender(<RouteDrcReport drc={{ error: "kicad-cli pcb drc wrote no report" }} />);
    expect(screen.getByText(/DRC failed to run/)).toBeInTheDocument();
  });
});
