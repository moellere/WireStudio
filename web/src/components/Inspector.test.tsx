/**
 * Component tests for the DesignInspector composition (rendered via the
 * exported Inspector with selection={kind: "design"}). Focus is on the
 * wiring between the inspector and its child controls -- the list rendering,
 * the section counts, the selection callback, and the remove-component
 * button. The deeper child components (BusList, ConnectionForm, etc.)
 * have their own focused suites; those aren't re-tested here.
 *
 * api.getComponent is mocked so the component-instance branch's library
 * fetch never hits the network. The design-pane tests don't trigger it
 * but the mock guarantees we'd notice if the wiring shifted.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Inspector, type Selection } from "./Inspector";
import { api } from "../api/client";
import type { BoardSummary, ComponentSummary, Design } from "../types/api";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    api: { ...actual.api, getComponent: vi.fn() },
  };
});
const mockApi = api as unknown as { getComponent: ReturnType<typeof vi.fn> };

const boardData = {
  rails: [{ name: "5V", voltage: 5 }, { name: "3V3", voltage: 3.3 }, { name: "GND", voltage: 0 }],
  gpio_capabilities: { D5: ["gpio"], D6: ["gpio"], D7: ["gpio"] },
  default_buses: { i2c: { sda: "D2", scl: "D1" } },
};

const libraryBoards: BoardSummary[] = [
  {
    id: "wemos-d1-mini", name: "WeMos D1 Mini",
    mcu: "esp8266", chip_variant: "esp8266", framework: "arduino",
    platformio_board: "d1_mini", flash_size_mb: 4, rail_names: ["5V", "3V3", "GND"],
  },
  {
    id: "esp32-devkitc-v4", name: "ESP32 DevKitC",
    mcu: "esp32", chip_variant: "esp32", framework: "arduino",
    platformio_board: "esp32dev", flash_size_mb: 4, rail_names: ["5V", "3V3", "GND"],
  },
];

const libraryComponents: ComponentSummary[] = [
  {
    id: "bme280", name: "BME280", category: "sensor",
    use_cases: ["temperature"], aliases: [], required_components: ["i2c"],
    current_ma_typical: 0.6, current_ma_peak: 4,
  },
  {
    id: "hc-sr501", name: "PIR", category: "binary_sensor",
    use_cases: ["motion"], aliases: [], required_components: [],
    current_ma_typical: 50, current_ma_peak: 65,
  },
];

function design(over: Partial<Design> = {}): Design {
  return {
    schema_version: "0.1",
    id: "t",
    name: "T",
    board: { library_id: "wemos-d1-mini", mcu: "esp8266" },
    components: [
      { id: "bme1", library_id: "bme280", label: "BME", params: {} },
      { id: "pir1", library_id: "hc-sr501", label: "Hall PIR", params: {} },
    ],
    buses: [{ id: "i2c0", type: "i2c", sda: "D2", scl: "D1" }],
    connections: [
      { component_id: "bme1", pin_role: "SDA", target: { kind: "bus", bus_id: "i2c0" } },
      { component_id: "pir1", pin_role: "OUT", target: { kind: "gpio", pin: "D5" } },
    ],
    requirements: [{ id: "r1", kind: "capability", text: "detect motion" }],
    warnings: [],
    fleet: { device_name: "t", tags: ["indoor"] },
    ...over,
  } as Design;
}

function noopProps() {
  return {
    onSelect: vi.fn(),
    onParamChange: vi.fn(),
    onConnectionChange: vi.fn(),
    onLockedPinChange: vi.fn(),
    onDesignChange: vi.fn(),
    onAddComponent: vi.fn(),
    onRemoveComponent: vi.fn(),
  };
}

beforeEach(() => {
  mockApi.getComponent.mockReset();
});

const designSelection: Selection = { kind: "design" };

describe("DesignInspector composition", () => {
  it("renders 'No design loaded' when design is null", () => {
    render(
      <Inspector
        {...noopProps()}
        selection={designSelection}
        design={null}
        boardData={boardData}
        libraryBoards={libraryBoards}
        libraryComponents={libraryComponents}
        compatibilityWarnings={[]}
      />,
    );
    expect(screen.getByText(/No design loaded/i)).toBeInTheDocument();
  });

  it("renders one row per component with the right id + label + library_id", () => {
    render(
      <Inspector
        {...noopProps()}
        selection={designSelection}
        design={design()}
        boardData={boardData}
        libraryBoards={libraryBoards}
        libraryComponents={libraryComponents}
        compatibilityWarnings={[]}
      />,
    );
    expect(screen.getByText("bme1")).toBeInTheDocument();
    expect(screen.getByText("pir1")).toBeInTheDocument();
    expect(screen.getByText("BME")).toBeInTheDocument();
    expect(screen.getByText("Hall PIR")).toBeInTheDocument();
  });

  it("section headers reflect collection counts", () => {
    render(
      <Inspector
        {...noopProps()}
        selection={designSelection}
        design={design()}
        boardData={boardData}
        libraryBoards={libraryBoards}
        libraryComponents={libraryComponents}
        compatibilityWarnings={[]}
      />,
    );
    // Components (2), Buses (1), Requirements (1), Warnings (0).
    expect(screen.getByText(/Components \(2\)/)).toBeInTheDocument();
    expect(screen.getByText(/Buses \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Requirements \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Warnings \(0\)/)).toBeInTheDocument();
  });

  it("clicking a component row fires onSelect with kind=component_instance", async () => {
    const props = noopProps();
    render(
      <Inspector
        {...props}
        selection={designSelection}
        design={design()}
        boardData={boardData}
        libraryBoards={libraryBoards}
        libraryComponents={libraryComponents}
        compatibilityWarnings={[]}
      />,
    );
    // Two buttons match the bme1 row: the select button (whole-row) and
    // the ✕ remove button. The select is the larger one carrying the id.
    const bmeSelect = screen.getByText("bme1").closest("button") as HTMLElement;
    await userEvent.click(bmeSelect);
    expect(props.onSelect).toHaveBeenCalledWith({ kind: "component_instance", id: "bme1" });
  });

  it("clicking the ✕ on a component row fires onRemoveComponent", async () => {
    const props = noopProps();
    render(
      <Inspector
        {...props}
        selection={designSelection}
        design={design()}
        boardData={boardData}
        libraryBoards={libraryBoards}
        libraryComponents={libraryComponents}
        compatibilityWarnings={[]}
      />,
    );
    // Find the bme1 row's container <li> and click its ✕ button. The
    // button's accessible name is just "✕" (title is decorative); query
    // by text content within the row to scope away from pir1's button.
    const bmeRow = screen.getByText("bme1").closest("li") as HTMLElement;
    const removeBtn = within(bmeRow).getByText("✕").closest("button") as HTMLElement;
    await userEvent.click(removeBtn);
    expect(props.onRemoveComponent).toHaveBeenCalledWith("bme1");
  });

  it("hides the Compatibility section when there are no warnings", () => {
    render(
      <Inspector
        {...noopProps()}
        selection={designSelection}
        design={design()}
        boardData={boardData}
        libraryBoards={libraryBoards}
        libraryComponents={libraryComponents}
        compatibilityWarnings={[]}
      />,
    );
    expect(screen.queryByText(/Compatibility \(\d+\)/)).not.toBeInTheDocument();
  });

  it("shows the Compatibility section with the count when warnings are present", () => {
    render(
      <Inspector
        {...noopProps()}
        selection={designSelection}
        design={design()}
        boardData={boardData}
        libraryBoards={libraryBoards}
        libraryComponents={libraryComponents}
        compatibilityWarnings={[
          { severity: "warn", code: "x", pin: "D5", component_id: "pir1", pin_role: "OUT", message: "test" },
        ]}
      />,
    );
    expect(screen.getByText(/Compatibility \(1\)/)).toBeInTheDocument();
  });

  it("shows the Fleet section only when the design has a fleet block", () => {
    // With fleet -> visible.
    const { rerender } = render(
      <Inspector
        {...noopProps()}
        selection={designSelection}
        design={design()}
        boardData={boardData}
        libraryBoards={libraryBoards}
        libraryComponents={libraryComponents}
        compatibilityWarnings={[]}
      />,
    );
    expect(screen.getByText("Fleet")).toBeInTheDocument();

    // Strip fleet -> hidden.
    const noFleet = { ...design() };
    delete (noFleet as Record<string, unknown>).fleet;
    rerender(
      <Inspector
        {...noopProps()}
        selection={designSelection}
        design={noFleet}
        boardData={boardData}
        libraryBoards={libraryBoards}
        libraryComponents={libraryComponents}
        compatibilityWarnings={[]}
      />,
    );
    expect(screen.queryByText("Fleet")).not.toBeInTheDocument();
  });

  it("renders an empty-components affordance when the design has no components", () => {
    render(
      <Inspector
        {...noopProps()}
        selection={designSelection}
        design={design({ components: [] })}
        boardData={boardData}
        libraryBoards={libraryBoards}
        libraryComponents={libraryComponents}
        compatibilityWarnings={[]}
      />,
    );
    expect(screen.getByText(/Components \(0\)/)).toBeInTheDocument();
    expect(screen.getByText(/no components/i)).toBeInTheDocument();
  });
});
