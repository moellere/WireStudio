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
      meshtasticFirmwareStatus: vi.fn(),
      meshtasticFirmware: vi.fn(),
      circuitpythonFirmwareStatus: vi.fn(),
      circuitpythonFirmware: vi.fn(),
      circuitpythonCode: vi.fn(),
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
  meshtasticFirmwareStatus: ReturnType<typeof vi.fn>;
  meshtasticFirmware: ReturnType<typeof vi.fn>;
  circuitpythonFirmwareStatus: ReturnType<typeof vi.fn>;
  circuitpythonFirmware: ReturnType<typeof vi.fn>;
  circuitpythonCode: ReturnType<typeof vi.fn>;
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
  mockApi.meshtasticFirmwareStatus.mockReset().mockResolvedValue({
    available: true,
    version: "v2.6.11.60ec05e",
    boards: ["heltec-wifi-lora32-v3", "ttgo-t-beam"],
    reason: null,
  });
  mockApi.circuitpythonFirmwareStatus.mockReset().mockResolvedValue({
    available: true,
    version: "10.2.1",
    boards: ["heltec-wifi-lora32-v3", "heltec-wifi-lora32-v4"],
    generic: ["heltec-wifi-lora32-v4"],
    images: {
      "heltec-wifi-lora32-v3": "heltec_esp32s3_wifi_lora_v3",
      "heltec-wifi-lora32-v4": "heltec_esp32s3_wifi_lora_v3",
    },
    reason: null,
  });
  mockApi.circuitpythonCode.mockReset().mockResolvedValue("import board\n");
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

  it("meshtastic flashes only mapped radio boards", async () => {
    renderDialog();
    await userEvent.click(screen.getByRole("button", { name: /meshtastic/i }));
    await waitFor(() =>
      expect(screen.getByText(/no meshtastic firmware mapping/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /flash meshtastic/i })).toBeDisabled();
  });

  it("circuitpython rejects unsupported (esp8266) boards", async () => {
    renderDialog();
    await userEvent.click(screen.getByRole("button", { name: /circuitpython/i }));
    await waitFor(() =>
      expect(screen.getByText(/no circuitpython build for/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /flash circuitpython/i })).toBeDisabled();
  });

  it("circuitpython enables flashing and warns on a generic image", async () => {
    const v4Design = {
      ...design,
      board: { library_id: "heltec-wifi-lora32-v4", mcu: "esp32s3" },
    } as Design;
    const v4Boards = [
      { id: "heltec-wifi-lora32-v4", name: "Heltec V4", chip_variant: "esp32s3" } as BoardSummary,
    ];
    renderDialog({ design: v4Design, boards: v4Boards });
    await userEvent.click(screen.getByRole("button", { name: /circuitpython/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /flash circuitpython/i })).toBeEnabled(),
    );
    expect(screen.getByText(/no official circuitpython build/i)).toBeInTheDocument();
  });

  it("meshtastic enables flashing for a supported board", async () => {
    const heltecDesign = {
      ...design,
      board: { library_id: "heltec-wifi-lora32-v3", mcu: "esp32s3" },
    } as Design;
    const heltecBoards = [
      { id: "heltec-wifi-lora32-v3", name: "Heltec V3", chip_variant: "esp32s3" } as BoardSummary,
    ];
    renderDialog({ design: heltecDesign, boards: heltecBoards });
    await userEvent.click(screen.getByRole("button", { name: /meshtastic/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /flash meshtastic/i })).toBeEnabled(),
    );
    expect(screen.getByText(/v2\.6\.11\.60ec05e/)).toBeInTheDocument();
  });
});
