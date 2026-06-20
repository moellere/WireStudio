/**
 * Component tests for LorawanProvisionEsphomeDialog. Three surfaces:
 *
 *   1. Eligibility gating -- the dialog refuses to call the endpoint when
 *      the design isn't external-component-shaped, and the Provision button
 *      stays disabled while the DevEUI is malformed.
 *   2. The provision flow -- on success the secrets block renders, the
 *      activation poll starts, and the AppKey copies to the clipboard.
 *   3. Error paths -- a 422 from the server surfaces in the dialog with the
 *      detail body, and the activation polling stops on join landing.
 *
 * The api/client surface is mocked at the import boundary; no network calls.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { LorawanProvisionEsphomeDialog } from "./LorawanProvisionEsphomeDialog";
import { api, ApiError } from "../api/client";
import type { Design } from "../types/api";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    api: {
      ...actual.api,
      lorawanChirpstackStatus: vi.fn(),
      lorawanProvisionEsphome: vi.fn(),
      lorawanActivation: vi.fn(),
      fleetPush: vi.fn(),
    },
  };
});

// usb-detect.ts dynamic-imports esptool-js, which is browser-only. Mock both
// functions so the WebSerial detect button can be exercised in jsdom.
vi.mock("../lib/usb-detect", () => ({
  detectChip: vi.fn(),
  isWebSerialSupported: vi.fn(() => "yes"),
}));

import { detectChip, isWebSerialSupported } from "../lib/usb-detect";
const mockDetectChip = detectChip as unknown as ReturnType<typeof vi.fn>;
const mockSupported = isWebSerialSupported as unknown as ReturnType<typeof vi.fn>;

const mockApi = api as unknown as {
  lorawanChirpstackStatus: ReturnType<typeof vi.fn>;
  lorawanProvisionEsphome: ReturnType<typeof vi.fn>;
  lorawanActivation: ReturnType<typeof vi.fn>;
  fleetPush: ReturnType<typeof vi.fn>;
};

function design(overrides: Partial<Design> = {}): Design {
  return {
    schema_version: "0.1",
    id: "lw-spike",
    name: "LoRaWAN spike",
    target: "esphome",
    board: { library_id: "ttgo-lora32-v1", mcu: "esp32", framework: "arduino" },
    components: [{ id: "battery", library_id: "adc", label: "Battery" }],
    buses: [],
    connections: [],
    requirements: [],
    warnings: [],
    lorawan: {
      region: "US915",
      sub_band: 2,
      payload: [{ sensor: "battery" }],
    },
    ...overrides,
  } as unknown as Design;
}

beforeEach(() => {
  mockApi.lorawanChirpstackStatus.mockReset();
  // Default to a reachable ChirpStack; the unavailable case is its own test.
  mockApi.lorawanChirpstackStatus.mockResolvedValue({
    available: true,
    url: "chirpstack:8080",
    reason: null,
  });
  mockApi.lorawanProvisionEsphome.mockReset();
  mockApi.lorawanActivation.mockReset();
  mockApi.fleetPush.mockReset();
  mockDetectChip.mockReset();
  mockSupported.mockReturnValue("yes");
});

afterEach(() => {
  vi.useRealTimers();
});

describe("eligibility gating", () => {
  it("hides the provision button when target is not 'esphome' and shows guidance", () => {
    render(
      <LorawanProvisionEsphomeDialog
        design={design({ target: "lorawan" } as Partial<Design>)}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText(/isn't eligible/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Provision →/i })).toBeNull();
  });

  it("hides the provision button when lorawan.payload is empty and shows guidance", () => {
    render(
      <LorawanProvisionEsphomeDialog
        design={design({
          lorawan: { region: "US915", sub_band: 2, payload: [] },
        } as Partial<Design>)}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText(/isn't eligible/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Provision →/i })).toBeNull();
  });

  it("disables Provision until the DevEUI is 16 hex chars", async () => {
    const user = userEvent.setup();
    render(<LorawanProvisionEsphomeDialog design={design()} onClose={() => {}} />);

    const btn = screen.getByRole("button", { name: /Provision →/i });
    expect(btn).toBeDisabled();

    const input = screen.getByPlaceholderText(/70b3d57ed0001234/i);
    await user.type(input, "70b3d57ed0001234");
    expect(btn).toBeEnabled();
  });

  it("flags a non-hex DevEUI inline", async () => {
    const user = userEvent.setup();
    render(<LorawanProvisionEsphomeDialog design={design()} onClose={() => {}} />);

    await user.type(screen.getByPlaceholderText(/70b3d57ed0001234/i), "not-hex");
    expect(screen.getByText(/Expected 16 hex characters/i)).toBeTruthy();
  });
});

describe("successful provision flow", () => {
  it("renders the secrets block and starts polling activation on success", async () => {
    const user = userEvent.setup();
    mockApi.lorawanProvisionEsphome.mockResolvedValue({
      secrets: {
        dev_eui: "70b3d57ed0001234",
        join_eui: "0000000000000000",
        app_key: "00112233445566778899aabbccddeeff",
      },
      chirpstack: { application_id: "app-1", device_profile_id: "dp-1" },
      band: "US915",
      sub_band: 2,
    });
    mockApi.lorawanActivation.mockResolvedValue({
      dev_eui: "70b3d57ed0001234",
      joined: false,
    });

    render(<LorawanProvisionEsphomeDialog design={design()} onClose={() => {}} />);
    await user.type(screen.getByPlaceholderText(/70b3d57ed0001234/i), "70b3d57ed0001234");
    await user.click(screen.getByRole("button", { name: /Provision →/i }));

    await waitFor(() => {
      expect(mockApi.lorawanProvisionEsphome).toHaveBeenCalledWith({
        dev_eui: "70b3d57ed0001234",
        design: expect.objectContaining({ id: "lw-spike" }),
      });
    });

    // Secrets render in the textarea (readonly, copy-friendly).
    const textarea = await screen.findByDisplayValue(/dev_eui:\s+"70b3d57ed0001234"/);
    expect(textarea.tagName).toBe("TEXTAREA");
    expect((textarea as HTMLTextAreaElement).readOnly).toBe(true);
    // AppKey is shown so the user can copy it (and only this once, server-side).
    expect((textarea as HTMLTextAreaElement).value).toContain(
      'app_key:  "00112233445566778899aabbccddeeff"',
    );

    // Activation poll fired on success.
    await waitFor(() => expect(mockApi.lorawanActivation).toHaveBeenCalledWith("70b3d57ed0001234"));
    expect(screen.getByText(/waiting for OTAA join/i)).toBeTruthy();
  });

  it("renders the joined state when activation poll reports joined=true", async () => {
    const user = userEvent.setup();
    mockApi.lorawanProvisionEsphome.mockResolvedValue({
      secrets: { dev_eui: "70b3d57ed0001234", join_eui: "0000000000000000", app_key: "ff".repeat(16) },
      chirpstack: { application_id: "app-1", device_profile_id: "dp-1" },
      band: "US915",
      sub_band: 2,
    });
    mockApi.lorawanActivation.mockResolvedValue({
      dev_eui: "70b3d57ed0001234",
      joined: true,
      dev_addr: "01020304",
      f_cnt_up: 7,
    });

    render(<LorawanProvisionEsphomeDialog design={design()} onClose={() => {}} />);
    await user.type(screen.getByPlaceholderText(/70b3d57ed0001234/i), "70b3d57ed0001234");
    await user.click(screen.getByRole("button", { name: /Provision →/i }));

    expect(await screen.findByText(/joined ·/i)).toBeTruthy();
    expect(screen.getByText(/01020304/)).toBeTruthy();
    expect(screen.getByText(/uplink frames: 7/)).toBeTruthy();
  });

  it("hides the Provision button once a result lands; Cancel turns into Done", async () => {
    const user = userEvent.setup();
    mockApi.lorawanProvisionEsphome.mockResolvedValue({
      secrets: { dev_eui: "70b3d57ed0001234", join_eui: "0000000000000000", app_key: "ff".repeat(16) },
      chirpstack: { application_id: "app-1", device_profile_id: "dp-1" },
      band: "US915",
      sub_band: 2,
    });
    mockApi.lorawanActivation.mockResolvedValue({ dev_eui: "70b3d57ed0001234", joined: false });

    render(<LorawanProvisionEsphomeDialog design={design()} onClose={() => {}} />);
    await user.type(screen.getByPlaceholderText(/70b3d57ed0001234/i), "70b3d57ed0001234");
    await user.click(screen.getByRole("button", { name: /Provision →/i }));

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /Provision →/i })).toBeNull(),
    );
    expect(screen.getByRole("button", { name: /^Done$/i })).toBeTruthy();
  });
});

describe("chirpstack reachability gating", () => {
  it("disables Provision and renders the reason when /lorawan/chirpstack/status reports unavailable", async () => {
    mockApi.lorawanChirpstackStatus.mockResolvedValue({
      available: false,
      url: "chirpstack:8080",
      reason: "ChirpStack unreachable: UNAUTHENTICATED: ",
    });

    render(<LorawanProvisionEsphomeDialog design={design()} onClose={() => {}} />);
    // Banner with the gRPC reason renders.
    await waitFor(() =>
      expect(screen.getByText(/ChirpStack unavailable/i)).toBeTruthy(),
    );
    expect(screen.getByText(/UNAUTHENTICATED/i)).toBeTruthy();
    // Provision stays disabled even with a valid DevEUI typed -- there's
    // nothing useful to do when the server can't be reached.
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText(/70b3d57ed0001234/i), "70b3d57ed0001234");
    const provisionBtn = screen.getByRole("button", { name: /Provision →/i });
    expect((provisionBtn as HTMLButtonElement).disabled).toBe(true);
    expect(mockApi.lorawanProvisionEsphome).not.toHaveBeenCalled();
  });
});

describe("error path", () => {
  it("renders the server detail when provision returns 422", async () => {
    const user = userEvent.setup();
    mockApi.lorawanProvisionEsphome.mockRejectedValue(
      new ApiError(422, "POST /lorawan/provision-esphome -> 422", {
        detail: "design.lorawan.payload must be non-empty for the ESPHome external-component path",
      }),
    );

    render(<LorawanProvisionEsphomeDialog design={design()} onClose={() => {}} />);
    await user.type(screen.getByPlaceholderText(/70b3d57ed0001234/i), "70b3d57ed0001234");
    await user.click(screen.getByRole("button", { name: /Provision →/i }));

    expect(await screen.findByText(/422: design\.lorawan\.payload/i)).toBeTruthy();
    // The result block didn't render, so Provision stays available for a retry.
    expect(screen.getByRole("button", { name: /Provision →/i })).toBeTruthy();
  });
});

describe("DevEUI auto-derive from chip", () => {
  it("fills the DevEUI field from the eFuse MAC and shows a chip + MAC hint", async () => {
    const user = userEvent.setup();
    // 10:52:1c:66:b6:e0 -> EUI-64 by inserting 0xFFFE → 10521cfffe66b6e0
    mockDetectChip.mockResolvedValue({ chipName: "ESP32-D0WD-V3", mac: "10:52:1c:66:b6:e0" });

    render(<LorawanProvisionEsphomeDialog design={design()} onClose={() => {}} />);
    await user.click(screen.getByRole("button", { name: /Detect from chip/i }));

    await waitFor(() => {
      const input = screen.getByPlaceholderText(/70b3d57ed0001234/i) as HTMLInputElement;
      expect(input.value).toBe("10521cfffe66b6e0");
    });
    expect(screen.getByText(/Derived from ESP32-D0WD-V3.*10:52:1c:66:b6:e0/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Provision →/i })).toBeEnabled();
  });

  it("surfaces a friendly error when the chip detects but no MAC is available", async () => {
    const user = userEvent.setup();
    mockDetectChip.mockResolvedValue({ chipName: "ESP32-D0WD-V3", mac: undefined });

    render(<LorawanProvisionEsphomeDialog design={design()} onClose={() => {}} />);
    await user.click(screen.getByRole("button", { name: /Detect from chip/i }));

    expect(await screen.findByText(/no MAC available/i)).toBeTruthy();
    expect((screen.getByPlaceholderText(/70b3d57ed0001234/i) as HTMLInputElement).value).toBe("");
  });

  it("surfaces detectChip errors (user cancel, sync failure) inline", async () => {
    const user = userEvent.setup();
    mockDetectChip.mockRejectedValue(new Error("port-picker dismissed"));

    render(<LorawanProvisionEsphomeDialog design={design()} onClose={() => {}} />);
    await user.click(screen.getByRole("button", { name: /Detect from chip/i }));

    expect(await screen.findByText(/detect failed: port-picker dismissed/i)).toBeTruthy();
  });

  it("disables Detect when WebSerial isn't available and explains why", () => {
    mockSupported.mockReturnValue("no");

    render(<LorawanProvisionEsphomeDialog design={design()} onClose={() => {}} />);
    expect(screen.getByRole("button", { name: /Detect from chip/i })).toBeDisabled();
    expect(screen.getByText(/WebSerial isn't available/i)).toBeTruthy();
    expect(mockDetectChip).not.toHaveBeenCalled();
  });

  it("clears the detection hint when the user manually edits the DevEUI", async () => {
    const user = userEvent.setup();
    mockDetectChip.mockResolvedValue({ chipName: "ESP32-D0WD-V3", mac: "10:52:1c:66:b6:e0" });

    render(<LorawanProvisionEsphomeDialog design={design()} onClose={() => {}} />);
    await user.click(screen.getByRole("button", { name: /Detect from chip/i }));
    await waitFor(() => expect(screen.queryByText(/Derived from/i)).toBeTruthy());

    await user.type(screen.getByPlaceholderText(/70b3d57ed0001234/i), "0");
    expect(screen.queryByText(/Derived from/i)).toBeNull();
  });
});

describe("push to fleet", () => {
  async function provisionFirst(user: ReturnType<typeof userEvent.setup>) {
    mockApi.lorawanProvisionEsphome.mockResolvedValue({
      secrets: {
        dev_eui: "70b3d57ed0001234",
        join_eui: "0000000000000000",
        app_key: "00112233445566778899aabbccddeeff",
      },
      chirpstack: { application_id: "app-1", device_profile_id: "dp-1" },
      band: "US915",
      sub_band: 2,
    });
    mockApi.lorawanActivation.mockResolvedValue({ dev_eui: "70b3d57ed0001234", joined: false });
    await user.type(screen.getByPlaceholderText(/70b3d57ed0001234/i), "70b3d57ed0001234");
    await user.click(screen.getByRole("button", { name: /Provision →/i }));
    // Wait for the success block (and the push button) to render.
    await waitFor(() => expect(screen.getByRole("button", { name: /Push to fleet →/i })).toBeTruthy());
  }

  it("hides the push button until provision succeeds", () => {
    render(<LorawanProvisionEsphomeDialog design={design()} onClose={() => {}} />);
    expect(screen.queryByRole("button", { name: /Push to fleet →/i })).toBeNull();
  });

  it("posts the secrets minted by provision-esphome through to /fleet/push", async () => {
    const user = userEvent.setup();
    mockApi.fleetPush.mockResolvedValue({
      filename: "lw-spike.yaml",
      created: true,
      run_id: "run-1",
      enqueued: 1,
    });

    render(<LorawanProvisionEsphomeDialog design={design()} onClose={() => {}} />);
    await provisionFirst(user);
    await user.click(screen.getByRole("button", { name: /Push to fleet →/i }));

    await waitFor(() => {
      expect(mockApi.fleetPush).toHaveBeenCalledWith({
        design: expect.objectContaining({ id: "lw-spike" }),
        compile: true,
        lorawan_secrets: {
          dev_eui: "70b3d57ed0001234",
          join_eui: "0000000000000000",
          app_key: "00112233445566778899aabbccddeeff",
        },
      });
    });
    // Text is split across nested <code> elements; assert on the parts
    // separately rather than reaching for a regex across element boundaries.
    expect(await screen.findByText(/Created/i)).toBeTruthy();
    expect(screen.getByText("lw-spike.yaml")).toBeTruthy();
    expect(screen.getByText("run-1")).toBeTruthy();
  });

  it("disables the push button after a successful push (no double-push)", async () => {
    const user = userEvent.setup();
    mockApi.fleetPush.mockResolvedValue({
      filename: "lw-spike.yaml",
      created: true,
      run_id: null,
      enqueued: 0,
    });

    render(<LorawanProvisionEsphomeDialog design={design()} onClose={() => {}} />);
    await provisionFirst(user);
    await user.click(screen.getByRole("button", { name: /Push to fleet →/i }));

    await waitFor(() => expect(screen.getByRole("button", { name: /^Pushed$/i })).toBeDisabled());
  });

  it("surfaces the server detail on fleet push failure (e.g. 503 unconfigured)", async () => {
    const user = userEvent.setup();
    mockApi.fleetPush.mockRejectedValue(
      new ApiError(503, "POST /fleet/push -> 503", {
        detail: "fleet not configured (set FLEET_URL and FLEET_TOKEN)",
      }),
    );

    render(<LorawanProvisionEsphomeDialog design={design()} onClose={() => {}} />);
    await provisionFirst(user);
    await user.click(screen.getByRole("button", { name: /Push to fleet →/i }));

    expect(await screen.findByText(/push failed: 503: fleet not configured/i)).toBeTruthy();
    // Pre-failed state — Push to fleet stays available for a retry.
    expect(screen.getByRole("button", { name: /Push to fleet →/i })).toBeEnabled();
  });
});
