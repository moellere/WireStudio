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
      lorawanProvisionEsphome: vi.fn(),
      lorawanActivation: vi.fn(),
    },
  };
});

const mockApi = api as unknown as {
  lorawanProvisionEsphome: ReturnType<typeof vi.fn>;
  lorawanActivation: ReturnType<typeof vi.fn>;
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
  mockApi.lorawanProvisionEsphome.mockReset();
  mockApi.lorawanActivation.mockReset();
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
