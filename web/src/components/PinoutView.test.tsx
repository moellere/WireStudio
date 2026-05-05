/**
 * Component tests for PinoutView. Focused on the drag-and-drop wiring:
 * dropping a connection chip onto a board pin fires onChange with the
 * right { kind: "gpio", pin } payload, conflict detection paints the
 * occupied pins in the rose tone, and the empty states render the
 * informational fallbacks.
 *
 * jsdom's HTML5 drag-and-drop is minimal but sufficient: we synthesize
 * the dragstart -> drop sequence with userEvent and a hand-built
 * DataTransfer stub.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { PinoutView } from "./PinoutView";
import type { ComponentInstance, ConnectionRow } from "../lib/design";

const board = {
  GPIO0:  ["boot", "strap", "boot_high"],
  GPIO5:  ["gpio", "spi_cs", "boot_high"],
  GPIO13: ["gpio", "adc", "adc2", "pwm"],
  GPIO34: ["gpio", "adc", "adc1", "input_only"],
};

const instance: ComponentInstance = { id: "pir1", library_id: "hc-sr501", label: "PIR" };

function gpioRow(pinRole: string, pin: string, index = 0): ConnectionRow {
  return {
    index, component_id: "pir1", pin_role: pinRole,
    target: { kind: "gpio", pin }, locked_pin: null,
  };
}

function railRow(): ConnectionRow {
  return {
    index: 99, component_id: "pir1", pin_role: "VCC",
    target: { kind: "rail", rail: "5V" }, locked_pin: null,
  };
}

/** Build a DataTransfer-shaped stub that records set/getData. jsdom's
 *  DataTransfer is incomplete; this is enough for the drag-drop path. */
function makeDataTransfer() {
  const store = new Map<string, string>();
  return {
    setData: (mime: string, value: string) => store.set(mime, value),
    getData: (mime: string) => store.get(mime) ?? "",
    effectAllowed: "uninitialized",
  } as unknown as DataTransfer;
}

describe("PinoutView empty states", () => {
  it("warns when the board has no gpio_capabilities", () => {
    render(
      <PinoutView
        rows={[gpioRow("OUT", "")]}
        allConnections={[gpioRow("OUT", "")]}
        instance={instance}
        gpioCapabilities={{}}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText(/No board pinout available/i)).toBeInTheDocument();
  });

  it("warns when the component has no gpio connections to drag", () => {
    render(
      <PinoutView
        rows={[railRow()]}
        allConnections={[railRow()]}
        instance={instance}
        gpioCapabilities={board}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText(/no gpio connections to drag/i)).toBeInTheDocument();
  });
});

describe("PinoutView rendering", () => {
  it("lists every board pin with its capability badges", () => {
    render(
      <PinoutView
        rows={[gpioRow("OUT", "")]}
        allConnections={[gpioRow("OUT", "")]}
        instance={instance}
        gpioCapabilities={board}
        onChange={() => {}}
      />,
    );
    // Every board pin renders.
    for (const pin of Object.keys(board)) {
      expect(screen.getByTestId(`pin-${pin}`)).toBeInTheDocument();
    }
    // The ADC2 badge appears on GPIO13.
    const gpio13 = screen.getByTestId("pin-GPIO13");
    expect(within(gpio13).getByText("ADC2")).toBeInTheDocument();
    // input-only flag on GPIO34.
    expect(within(screen.getByTestId("pin-GPIO34")).getByText(/input only/i))
      .toBeInTheDocument();
  });

  it("annotates the pin currently bound to a connection on this instance", () => {
    render(
      <PinoutView
        rows={[gpioRow("OUT", "GPIO13")]}
        allConnections={[gpioRow("OUT", "GPIO13")]}
        instance={instance}
        gpioCapabilities={board}
        onChange={() => {}}
      />,
    );
    const gpio13 = screen.getByTestId("pin-GPIO13");
    expect(within(gpio13).getByText(/← OUT/)).toBeInTheDocument();
  });

  it("flags pins occupied by a different component as 'used by'", () => {
    const other: ConnectionRow = {
      index: 5, component_id: "led1", pin_role: "DATA",
      target: { kind: "gpio", pin: "GPIO5" }, locked_pin: null,
    };
    render(
      <PinoutView
        rows={[gpioRow("OUT", "")]}
        allConnections={[gpioRow("OUT", ""), other]}
        instance={instance}
        gpioCapabilities={board}
        onChange={() => {}}
      />,
    );
    const gpio5 = screen.getByTestId("pin-GPIO5");
    expect(within(gpio5).getByText(/used by led1\.DATA/i)).toBeInTheDocument();
  });
});

describe("PinoutView drag-and-drop", () => {
  it("dropping a draggable onto a board pin fires onChange with the gpio target", () => {
    const onChange = vi.fn();
    const row = gpioRow("OUT", "");
    render(
      <PinoutView
        rows={[row]}
        allConnections={[row]}
        instance={instance}
        gpioCapabilities={board}
        onChange={onChange}
      />,
    );
    const dt = makeDataTransfer();
    const drag = screen.getByTestId("drag-OUT");
    fireEvent.dragStart(drag, { dataTransfer: dt });
    expect(dt.getData("application/x-wirestudio-connection-index")).toBe(String(row.index));

    const target = screen.getByTestId("pin-GPIO13");
    fireEvent.dragOver(target, { dataTransfer: dt });
    fireEvent.drop(target, { dataTransfer: dt });

    expect(onChange).toHaveBeenCalledWith(row.index, { kind: "gpio", pin: "GPIO13" });
  });

  it("dropping with an empty payload is a no-op (defensive)", () => {
    const onChange = vi.fn();
    render(
      <PinoutView
        rows={[gpioRow("OUT", "")]}
        allConnections={[gpioRow("OUT", "")]}
        instance={instance}
        gpioCapabilities={board}
        onChange={onChange}
      />,
    );
    const target = screen.getByTestId("pin-GPIO13");
    fireEvent.drop(target, { dataTransfer: makeDataTransfer() });
    expect(onChange).not.toHaveBeenCalled();
  });
});
