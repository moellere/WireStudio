/**
 * Component tests for SchematicDialog. Covers the download-script path
 * (API call shape, success affirmation, error banner) and the inline
 * SVG preview, which is feature-gated on /design/kicad/render/status.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SchematicDialog } from "./SchematicDialog";
import { api } from "../api/client";
import type { Design, KicadRenderStatus } from "../types/api";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    api: {
      ...actual.api,
      kicadSchematic: vi.fn(),
      kicadRenderStatus: vi.fn(),
      kicadRender: vi.fn(),
    },
  };
});

const mockApi = api as unknown as {
  kicadSchematic: ReturnType<typeof vi.fn>;
  kicadRenderStatus: ReturnType<typeof vi.fn>;
  kicadRender: ReturnType<typeof vi.fn>;
};

const UNAVAILABLE: KicadRenderStatus = {
  available: false, kicad_cli: false, skidl: false, png: false,
  reason: "kicad-cli not on PATH",
};
const AVAILABLE: KicadRenderStatus = {
  available: true, kicad_cli: true, skidl: true, png: true, reason: null,
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
  mockApi.kicadRenderStatus.mockReset();
  mockApi.kicadRender.mockReset();
  mockApi.kicadRenderStatus.mockResolvedValue(UNAVAILABLE);
  (URL as unknown as { createObjectURL: () => string }).createObjectURL = vi.fn(() => "blob:fake");
  (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = vi.fn();
});
afterEach(() => {
  delete (URL as unknown as Record<string, unknown>).createObjectURL;
  delete (URL as unknown as Record<string, unknown>).revokeObjectURL;
});


describe("SchematicDialog — download script", () => {
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

describe("SchematicDialog — inline preview", () => {
  it("shows a notice when the renderer is unavailable", async () => {
    render(<SchematicDialog design={design} onClose={() => {}} />);
    await waitFor(() => screen.getByText(/render it locally instead/));
    expect(screen.queryByRole("button", { name: /Render schematic/ })).toBeNull();
  });

  it("renders an SVG preview when the renderer is available", async () => {
    mockApi.kicadRenderStatus.mockResolvedValue(AVAILABLE);
    mockApi.kicadRender.mockResolvedValue("<svg><rect/></svg>");
    render(<SchematicDialog design={design} onClose={() => {}} />);
    const btn = await screen.findByRole("button", { name: /Render schematic/ });
    await userEvent.click(btn);
    await waitFor(() => expect(mockApi.kicadRender).toHaveBeenCalledWith(design));
    await waitFor(() =>
      expect(screen.getByAltText("rendered schematic")).toHaveAttribute("src", "blob:fake"),
    );
  });

  it("surfaces a render failure in a rose banner", async () => {
    const { ApiError } = await vi.importActual<typeof import("../api/client")>(
      "../api/client",
    );
    mockApi.kicadRenderStatus.mockResolvedValue(AVAILABLE);
    mockApi.kicadRender.mockRejectedValue(
      new ApiError(500, "POST /design/kicad/render -> 500", {
        detail: "kicad-cli failed: bad symbol",
      }),
    );
    render(<SchematicDialog design={design} onClose={() => {}} />);
    const btn = await screen.findByRole("button", { name: /Render schematic/ });
    await userEvent.click(btn);
    await waitFor(() => screen.getByText(/kicad-cli failed: bad symbol/));
  });
});
