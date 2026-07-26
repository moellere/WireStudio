/**
 * The framework picker is the surface under test: each panel renders the
 * right affordance and the LoRaWAN choice delegates to the existing
 * dialog. Actual flashing needs WebSerial hardware and is not simulated.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { FlashDialog } from "./FlashDialog";
import { api } from "../api/client";
import type { BoardSummary, Design } from "../types/api";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    api: {
      ...actual.api,
      tasmotaFirmwareStatus: vi.fn(),
      tasmotaTemplate: vi.fn(),
      tasmotaFirmware: vi.fn(),
    },
  };
});

vi.mock("./LorawanFlashDialog", () => ({
  LorawanFlashDialog: () => <div data-testid="lorawan-dialog" />,
}));

const mockApi = api as unknown as {
  tasmotaFirmwareStatus: ReturnType<typeof vi.fn>;
  tasmotaTemplate: ReturnType<typeof vi.fn>;
  tasmotaFirmware: ReturnType<typeof vi.fn>;
};

const design: Design = {
  schema_version: "0.1",
  id: "smart-plug",
  name: "Smart plug",
  board: { library_id: "d1-mini", mcu: "esp8266" },
  components: [],
  buses: [],
  connections: [],
  requirements: [],
  warnings: [],
} as Design;

const boards: BoardSummary[] = [
  { id: "d1-mini", name: "D1 Mini", chip_variant: "esp8266" } as BoardSummary,
];

beforeEach(() => {
  mockApi.tasmotaFirmwareStatus.mockReset().mockResolvedValue({
    available: true,
    chips: ["esp8266"],
    reason: null,
  });
  mockApi.tasmotaTemplate.mockReset().mockResolvedValue({
    template: { NAME: "smart-plug", GPIO: [0], FLAG: 0, BASE: 18 },
    warnings: [],
  });
});

function renderDialog(overrides: Partial<Parameters<typeof FlashDialog>[0]> = {}) {
  return render(
    <FlashDialog
      design={design}
      boards={boards}
      onClose={() => {}}
      onOpenFleet={() => {}}
      {...overrides}
    />,
  );
}

describe("FlashDialog", () => {
  it("defaults to tasmota and derives the chip from the design board", async () => {
    renderDialog();
    await waitFor(() => expect(screen.getByText("esp8266")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /flash tasmota/i })).toBeEnabled();
  });

  it("disables flashing when the firmware proxy is unavailable", async () => {
    mockApi.tasmotaFirmwareStatus.mockResolvedValue({
      available: false,
      chips: [],
      reason: "OTA server unreachable",
    });
    renderDialog();
    await waitFor(() =>
      expect(screen.getByText(/firmware download unavailable/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /flash tasmota/i })).toBeDisabled();
  });

  it("esphome panel hands off to the fleet dialog", async () => {
    const onClose = vi.fn();
    const onOpenFleet = vi.fn();
    renderDialog({ onClose, onOpenFleet });
    await userEvent.click(screen.getByRole("button", { name: /esphome/i }));
    await userEvent.click(screen.getByRole("button", { name: /push to fleet/i }));
    expect(onClose).toHaveBeenCalled();
    expect(onOpenFleet).toHaveBeenCalled();
  });

  it("lorawan delegates to the existing flash dialog", async () => {
    renderDialog();
    await userEvent.click(screen.getByRole("button", { name: /lorawan/i }));
    expect(screen.getByTestId("lorawan-dialog")).toBeInTheDocument();
  });

  it("meshtastic stays disabled", () => {
    renderDialog();
    expect(screen.getByRole("button", { name: /meshtastic/i })).toBeDisabled();
  });
});
