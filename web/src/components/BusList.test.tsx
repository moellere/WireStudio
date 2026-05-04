/**
 * Component tests for BusList. Covers the surface that has non-trivial
 * state: the rename draft (commit on blur, revert on Esc, reject on
 * collision) and the inline compatibility-warning rendering.
 *
 * Render-only smoke tests (does the empty state appear, does the add
 * button enqueue the right type) are intentionally light -- BusList is
 * a thin presentation layer over the design.ts helpers, which already
 * have full unit coverage.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { BusList } from "./BusList";
import type { CompatibilityWarning, Design } from "../types/api";

function makeDesign(overrides: Partial<Design> = {}): Design {
  return {
    schema_version: "0.1",
    id: "t",
    name: "t",
    board: { library_id: "wemos-d1-mini", mcu: "esp8266" },
    components: [
      { id: "bme1", library_id: "bme280", label: "BME", params: {} },
    ],
    buses: [{ id: "i2c0", type: "i2c", sda: "D2", scl: "D1" }],
    connections: [
      { component_id: "bme1", pin_role: "SDA", target: { kind: "bus", bus_id: "i2c0" } },
    ],
    requirements: [],
    warnings: [],
    fleet: { device_name: "t", tags: [] },
    ...overrides,
  };
}

describe("BusList rendering", () => {
  it("shows empty state when there are no buses", () => {
    render(
      <BusList
        design={makeDesign({ buses: [] })}
        gpioPins={["D1", "D2"]}
        defaultBuses={{}}
        compatibilityWarnings={[]}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText("No buses.")).toBeInTheDocument();
  });

  it("renders one card per bus with id + type pill", () => {
    render(
      <BusList
        design={makeDesign()}
        gpioPins={["D1", "D2"]}
        defaultBuses={{}}
        compatibilityWarnings={[]}
        onChange={() => {}}
      />,
    );
    expect(screen.getByDisplayValue("i2c0")).toBeInTheDocument();
    // The type pill is a <span> beside the id input. The add-bus type
    // <select> also contains an "i2c" <option>, so disambiguate by tag.
    const i2cMatches = screen.getAllByText("i2c");
    expect(i2cMatches.some((n) => n.tagName === "SPAN")).toBe(true);
  });
});

describe("BusList rename draft", () => {
  it("commits on Enter and produces a renameBus call", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <BusList
        design={makeDesign()}
        gpioPins={["D1", "D2"]}
        defaultBuses={{}}
        compatibilityWarnings={[]}
        onChange={onChange}
      />,
    );
    const input = screen.getByDisplayValue("i2c0") as HTMLInputElement;
    await user.tripleClick(input);
    await user.keyboard("shared_i2c{Enter}");

    // onChange is called with an updater; apply it to a known-good design
    // and verify the bus + targeting connection both follow the rename.
    expect(onChange).toHaveBeenCalledTimes(1);
    const updater = onChange.mock.calls[0][0] as (d: Design) => Design;
    const next = updater(makeDesign());
    expect((next.buses as Array<Record<string, unknown>>)[0].id).toBe("shared_i2c");
    const conn = (next.connections as Array<{ target: { kind: string; bus_id?: string } }>)[0];
    expect(conn.target.bus_id).toBe("shared_i2c");
  });

  it("reverts on Escape without firing onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <BusList
        design={makeDesign()}
        gpioPins={["D1", "D2"]}
        defaultBuses={{}}
        compatibilityWarnings={[]}
        onChange={onChange}
      />,
    );
    const input = screen.getByDisplayValue("i2c0") as HTMLInputElement;
    await user.tripleClick(input);
    await user.keyboard("shared_i2c{Escape}");
    expect(input.value).toBe("i2c0");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("rejects a collision with another bus's id", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const design = makeDesign({
      buses: [
        { id: "i2c0", type: "i2c", sda: "D2", scl: "D1" },
        { id: "spi0", type: "spi", clk: "D5" },
      ],
    });
    render(
      <BusList
        design={design}
        gpioPins={["D1", "D2", "D5"]}
        defaultBuses={{}}
        compatibilityWarnings={[]}
        onChange={onChange}
      />,
    );
    const input = screen.getByDisplayValue("i2c0") as HTMLInputElement;
    await user.tripleClick(input);
    await user.keyboard("spi0");
    // Trigger commit by tabbing away to blur.
    await user.tab();
    expect(onChange).not.toHaveBeenCalled();
    // Field reverts to the canonical id.
    expect(input.value).toBe("i2c0");
  });

  it("ignores a no-op rename to the same id", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <BusList
        design={makeDesign()}
        gpioPins={["D1", "D2"]}
        defaultBuses={{}}
        compatibilityWarnings={[]}
        onChange={onChange}
      />,
    );
    const input = screen.getByDisplayValue("i2c0");
    await user.click(input);
    await user.tab();
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("BusList inline compat warnings", () => {
  const warning: CompatibilityWarning = {
    severity: "warn",
    code: "boot_strap_output",
    pin: "GPIO5",
    component_id: "spi0",
    pin_role: "CLK",
    message: "GPIO5 must be HIGH at boot.",
  };

  it("filters warnings to the matching bus card", () => {
    const design = makeDesign({
      buses: [
        { id: "i2c0", type: "i2c", sda: "D2", scl: "D1" },
        { id: "spi0", type: "spi", clk: "GPIO5" },
      ],
    });
    render(
      <BusList
        design={design}
        gpioPins={["D1", "D2", "GPIO5"]}
        defaultBuses={{}}
        compatibilityWarnings={[warning]}
        onChange={() => {}}
      />,
    );
    // Warning text appears once, under the spi0 card. Use the message as
    // the search anchor since it's stable.
    const found = screen.getByText(/GPIO5 must be HIGH at boot/i);
    expect(found).toBeInTheDocument();
  });

  it("does not render a warning that doesn't match any bus", () => {
    render(
      <BusList
        design={makeDesign()}
        gpioPins={["D1", "D2"]}
        defaultBuses={{}}
        compatibilityWarnings={[
          { ...warning, component_id: "ghost_bus" },
        ]}
        onChange={() => {}}
      />,
    );
    expect(
      screen.queryByText(/GPIO5 must be HIGH at boot/i),
    ).not.toBeInTheDocument();
  });
});
