/**
 * Component tests for SchematicDialog (0.9). The dialog is small but
 * exercises the same download-blob pattern as EnclosureDialog's
 * Generate tab; we verify the API call shape, the success affirmation,
 * and the error path.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SchematicDialog } from "./SchematicDialog";
import { api } from "../api/client";
import type { Design } from "../types/api";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    api: { ...actual.api, kicadSchematic: vi.fn() },
  };
});

const mockApi = api as unknown as {
  kicadSchematic: ReturnType<typeof vi.fn>;
};

const design: Design = {
  schema_version: "0.1",
  id: "garage-motion",
  name: "Garage motion",
  board: { library_id: "esp32-devkitc-v4", mcu: "esp32" },
  components: [],
  buses: [],
  connections: [],
  requirements: [],
  warnings: [],
} as Design;

beforeEach(() => {
  mockApi.kicadSchematic.mockReset();
  (URL as unknown as { createObjectURL: () => string }).createObjectURL = vi.fn(() => "blob:fake");
  (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = vi.fn();
});
afterEach(() => {
  delete (URL as unknown as Record<string, unknown>).createObjectURL;
  delete (URL as unknown as Record<string, unknown>).revokeObjectURL;
});


describe("SchematicDialog", () => {
  it("downloads on click and shows the success state", async () => {
    mockApi.kicadSchematic.mockResolvedValue("from skidl import Part\n");
    render(<SchematicDialog design={design} onClose={() => {}} />);
    const btn = await screen.findByRole("button", { name: /Download \.skidl\.py/ });
    await userEvent.click(btn);
    await waitFor(() => expect(mockApi.kicadSchematic).toHaveBeenCalledWith(design));
    await waitFor(() => screen.getByText(/Downloaded ✓/));
  });

  it("renders a usage snippet referencing the design id", () => {
    render(<SchematicDialog design={design} onClose={() => {}} />);
    expect(screen.getByText(/python garage-motion\.skidl\.py/)).toBeInTheDocument();
    expect(screen.getByText(/produces garage-motion\.kicad_sch/)).toBeInTheDocument();
  });

  it("surfaces a 422 detail in a rose banner", async () => {
    const { ApiError } = await vi.importActual<typeof import("../api/client")>(
      "../api/client",
    );
    mockApi.kicadSchematic.mockRejectedValue(
      new ApiError(422, "POST /design/kicad/schematic -> 422", {
        detail: "design.id is required",
      }),
    );
    render(<SchematicDialog design={design} onClose={() => {}} />);
    const btn = await screen.findByRole("button", { name: /Download \.skidl\.py/ });
    await userEvent.click(btn);
    await waitFor(() => screen.getByText(/design.id is required/));
  });

  it("links to the SKiDL docs", () => {
    render(<SchematicDialog design={design} onClose={() => {}} />);
    const link = screen.getByRole("link", { name: /SKiDL/i });
    expect(link).toHaveAttribute("href", "https://devbisme.github.io/skidl/");
  });

  it("closes when the user clicks Close", async () => {
    const onClose = vi.fn();
    render(<SchematicDialog design={design} onClose={onClose} />);
    await userEvent.click(screen.getByRole("button", { name: /Close/ }));
    expect(onClose).toHaveBeenCalled();
  });
});
