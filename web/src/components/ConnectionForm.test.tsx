/**
 * Component tests for ConnectionForm. Focused on the per-row LockToggle
 * (3-state machine with divergence indicator), since the rest of the
 * form is a thin shim over <select>/<input>.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ConnectionForm } from "./ConnectionForm";
import type { ConnectionRow } from "../lib/design";
import type { Design } from "../types/api";

function makeDesign(): Design {
  return {
    schema_version: "0.1",
    id: "t",
    name: "t",
    board: { library_id: "wemos-d1-mini", mcu: "esp8266" },
    components: [],
    buses: [],
    connections: [],
    requirements: [],
    warnings: [],
  } as Design;
}

const board = {
  rails: [{ name: "5V", voltage: 5 }, { name: "GND", voltage: 0 }],
  gpio_capabilities: { D5: ["gpio"], D6: ["gpio"], D7: ["gpio"] },
};

function gpioRow(over: Partial<ConnectionRow> = {}): ConnectionRow {
  return {
    index: 0,
    component_id: "c1",
    pin_role: "OUT",
    target: { kind: "gpio", pin: "D5" },
    locked_pin: null,
    ...over,
  };
}

describe("LockToggle", () => {
  it("shows '🔓 lock' when no lock is set and the pin is bound", () => {
    render(
      <ConnectionForm
        rows={[gpioRow()]}
        design={makeDesign()}
        boardData={board}
        libraryComponents={[]}
        onChange={() => {}}
        onLockedPinChange={() => {}}
      />,
    );
    const btn = screen.getByRole("button", { name: /lock/ });
    expect(btn).toHaveTextContent("🔓 lock");
    expect(btn).not.toBeDisabled();
  });

  it("disables the lock button when no pin is bound yet", () => {
    render(
      <ConnectionForm
        rows={[gpioRow({ target: { kind: "gpio", pin: "" } })]}
        design={makeDesign()}
        boardData={board}
        libraryComponents={[]}
        onChange={() => {}}
        onLockedPinChange={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /lock/ })).toBeDisabled();
  });

  it("calls onLockedPinChange with the bound pin when the user clicks lock", async () => {
    const onLockedPinChange = vi.fn();
    render(
      <ConnectionForm
        rows={[gpioRow()]}
        design={makeDesign()}
        boardData={board}
        libraryComponents={[]}
        onChange={() => {}}
        onLockedPinChange={onLockedPinChange}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /lock/ }));
    expect(onLockedPinChange).toHaveBeenCalledWith("c1", "OUT", "D5");
  });

  it("shows the locked badge in the in-sync state and clicking it clears the lock", async () => {
    const onLockedPinChange = vi.fn();
    render(
      <ConnectionForm
        rows={[gpioRow({ locked_pin: "D5" })]}
        design={makeDesign()}
        boardData={board}
        libraryComponents={[]}
        onChange={() => {}}
        onLockedPinChange={onLockedPinChange}
      />,
    );
    const badge = screen.getByRole("button", { name: /D5/i });
    expect(badge).toHaveTextContent("🔒 D5");
    expect(badge).toHaveClass("border-emerald-600/50");
    expect(screen.queryByText(/will flag a mismatch/i)).not.toBeInTheDocument();
    await userEvent.click(badge);
    expect(onLockedPinChange).toHaveBeenCalledWith("c1", "OUT", null);
  });

  it("renders the diverged variant + inline mismatch hint when bound pin differs from lock", () => {
    render(
      <ConnectionForm
        rows={[gpioRow({ target: { kind: "gpio", pin: "D7" }, locked_pin: "D5" })]}
        design={makeDesign()}
        boardData={board}
        libraryComponents={[]}
        onChange={() => {}}
        onLockedPinChange={() => {}}
      />,
    );
    const badge = screen.getByRole("button", { name: /D5/i });
    expect(badge).toHaveTextContent("🔒 D5");
    expect(badge).toHaveClass("border-amber-600/50");
    // The inline warning appears below the row.
    expect(screen.getByText(/solver will flag a mismatch/i)).toBeInTheDocument();
    // And mentions both pins.
    expect(screen.getByText(/locked to/i).textContent).toMatch(/D5/);
    expect(screen.getByText(/locked to/i).textContent).toMatch(/D7/);
  });
});

describe("ConnectionForm row routing", () => {
  it("does not render the LockToggle for non-gpio targets", () => {
    render(
      <ConnectionForm
        rows={[
          {
            index: 0,
            component_id: "c1",
            pin_role: "VCC",
            target: { kind: "rail", rail: "5V" },
            locked_pin: null,
          },
        ]}
        design={makeDesign()}
        boardData={board}
        libraryComponents={[]}
        onChange={() => {}}
        onLockedPinChange={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: /lock/ })).not.toBeInTheDocument();
  });

  it("renders a friendly empty state when there are no connections", () => {
    render(
      <ConnectionForm
        rows={[]}
        design={makeDesign()}
        boardData={board}
        libraryComponents={[]}
        onChange={() => {}}
        onLockedPinChange={() => {}}
      />,
    );
    expect(screen.getByText(/no connections/i)).toBeInTheDocument();
  });
});
