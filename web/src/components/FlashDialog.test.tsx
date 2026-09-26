/**
 * The framework picker is the surface under test: each panel renders the
 * right affordance and the LoRaWAN choice delegates to the existing
 * dialog. Actual flashing needs WebSerial hardware and is not simulated.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { BootStatus, FlashDialog } from "./FlashDialog";
import { api } from "../api/client";
import type { BoardSummary, Design } from "../types/api";

const meshPush = vi.fn();
vi.mock("../lib/meshtastic", async () => {
  const actual = await vi.importActual<typeof import("../lib/meshtastic")>("../lib/meshtastic");
  return {
    ...actual,
    loadMeshtastic: vi.fn(async () => ({
      Protobuf: {
        Config: {
          Config_LoRaConfig_RegionCode: { UNSET: 0, US: 1, EU_868: 3 },
          Config_LoRaConfig_ModemPreset: { LONG_FAST: 0, SHORT_FAST: 4 },
        },
      },
    })),
    pushMeshtasticConfig: (...args: unknown[]) => meshPush(...args),
  };
});

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
      micropythonFirmwareStatus: vi.fn(),
      micropythonFirmware: vi.fn(),
      micropythonCode: vi.fn(),
      micropythonDesignCode: vi.fn(),
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
  micropythonFirmwareStatus: ReturnType<typeof vi.fn>;
  micropythonFirmware: ReturnType<typeof vi.fn>;
  micropythonCode: ReturnType<typeof vi.fn>;
  micropythonDesignCode: ReturnType<typeof vi.fn>;
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
  mockApi.micropythonFirmwareStatus.mockReset().mockResolvedValue({
    available: true,
    version: "1.25.0",
    boards: ["d1-mini", "heltec-wifi-lora32-v3"],
    images: { "d1-mini": "ESP8266_GENERIC", "heltec-wifi-lora32-v3": "ESP32_GENERIC_S3" },
    offsets: { "d1-mini": 0, "heltec-wifi-lora32-v3": 0 },
    reason: null,
  });
  mockApi.micropythonCode.mockReset().mockResolvedValue("from machine import Pin\n");
  mockApi.micropythonDesignCode.mockReset().mockResolvedValue({ code: "from machine import Pin\n", deps: [], warnings: [] });
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

  it("micropython covers the esp8266 board and offers the starter main.py", async () => {
    renderDialog();
    await userEvent.click(screen.getByRole("button", { name: /^micropython/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /flash micropython/i })).toBeEnabled(),
    );
    expect(screen.getByText(/ESP8266_GENERIC/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/starter main.py for this board/i)).toBeInTheDocument());
    expect(mockApi.micropythonCode).toHaveBeenCalledWith("d1-mini");
    expect(screen.getByRole("button", { name: /push main.py to a connected board/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /download main.py/i })).toBeInTheDocument();
  });

  it("micropython generates main.py from a design with components and lists the mip installs", async () => {
    mockApi.micropythonDesignCode.mockResolvedValue({
      code: "import bme280_float as bme280\n", deps: ["github:robert-hh/BME280/bme280_float.py"], warnings: ["x: skipped"],
    });
    const withParts = { ...design, components: [{ id: "c1", library_id: "bme280" }] } as unknown as Design;
    renderDialog({ design: withParts });
    await userEvent.click(screen.getByRole("button", { name: /^micropython/i }));
    await waitFor(() => expect(screen.getByText(/main.py generated from this design/i)).toBeInTheDocument());
    expect(screen.getByText(/mip.install\("github:robert-hh/)).toBeInTheDocument();
    expect(screen.getByText("x: skipped")).toBeInTheDocument();
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


describe("meshtastic configuration", () => {
  it("pushes the form's settings to a connected node", async () => {
    meshPush.mockReset().mockResolvedValue({ nodeNum: 0xabcd, longName: "garage-motion" });
    const requestPort = vi.fn(async () => ({}));
    Object.defineProperty(navigator, "serial", { value: { requestPort }, configurable: true });
    renderDialog();
    await userEvent.click(screen.getByRole("button", { name: /meshtastic/i }));
    await waitFor(() => expect(screen.getByTestId("meshtastic-config")).toBeInTheDocument());
    expect(screen.getByRole("option", { name: "EU_868" })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Region"), "3");
    await userEvent.clear(screen.getByLabelText("Channel name"));
    await userEvent.type(screen.getByLabelText("Channel name"), "home");
    await userEvent.click(screen.getByRole("button", { name: /configure connected node/i }));
    await waitFor(() => expect(screen.getByText(/Node !abcd/)).toBeInTheDocument());
    expect(requestPort).toHaveBeenCalled();
    const settings = meshPush.mock.calls[0][1] as { region: number; channelName: string; psk: string };
    expect(settings.region).toBe(3);
    expect(settings.channelName).toBe("home");
    expect(settings.psk).toBe("");
  });

  it("refuses a malformed channel key before touching the port", async () => {
    meshPush.mockReset();
    renderDialog();
    await userEvent.click(screen.getByRole("button", { name: /meshtastic/i }));
    await waitFor(() => expect(screen.getByTestId("meshtastic-config")).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText("Channel key"), "nope!!");
    await userEvent.click(screen.getByRole("button", { name: /configure connected node/i }));
    await waitFor(() => expect(screen.getByText(/PSK is not base64/)).toBeInTheDocument());
    expect(meshPush).not.toHaveBeenCalled();
  });
});

describe("BootStatus", () => {
  it("renders nothing without a verdict, then booted, not booted, and not verifiable", () => {
    const { container, rerender } = render(<BootStatus result={null} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<BootStatus result={{ ok: true, framework: "esphome", booted: true, checks: [{ stage: "boot", matched: true, proves: "every ESPHome component initialised", line: "[I][app:117]: setup() finished successfully!" }] }} />);
    expect(screen.getByText(/booted: every esphome component initialised/i)).toBeInTheDocument();
    rerender(<BootStatus result={{ ok: false, framework: "lorawan", booted: false, checks: [{ stage: "boot", matched: false, pattern: "wirestudio lorawan:", timeout_s: 45 }] }} />);
    expect(screen.getByText(/no boot marker within 45 s/i)).toBeInTheDocument();
    rerender(<BootStatus result={{ ok: false, framework: "circuitpython", error: "success is CIRCUITPY enumerating as USB mass storage" }} />);
    expect(screen.getByText(/boot not verified: success is circuitpy/i)).toBeInTheDocument();
  });
});
