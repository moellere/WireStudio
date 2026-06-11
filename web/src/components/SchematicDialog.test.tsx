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
import type { Design, FabStatus, KicadPcbStatus, KicadRenderStatus } from "../types/api";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    api: {
      ...actual.api,
      kicadSchematic: vi.fn(),
      kicadRenderStatus: vi.fn(),
      kicadRender: vi.fn(),
      kicadPcbStatus: vi.fn(),
      kicadPcb: vi.fn(),
      fabStatus: vi.fn(),
      fabBom: vi.fn(),
      fabCpl: vi.fn(),
      fabPackage: vi.fn(),
    },
  };
});

const mockApi = api as unknown as {
  kicadSchematic: ReturnType<typeof vi.fn>;
  kicadRenderStatus: ReturnType<typeof vi.fn>;
  kicadRender: ReturnType<typeof vi.fn>;
  kicadPcbStatus: ReturnType<typeof vi.fn>;
  kicadPcb: ReturnType<typeof vi.fn>;
  fabStatus: ReturnType<typeof vi.fn>;
  fabBom: ReturnType<typeof vi.fn>;
  fabCpl: ReturnType<typeof vi.fn>;
  fabPackage: ReturnType<typeof vi.fn>;
};

const UNAVAILABLE: KicadRenderStatus = {
  available: false, kicad_cli: false, skidl: false, png: false,
  reason: "kicad-cli not on PATH",
};
const AVAILABLE: KicadRenderStatus = {
  available: true, kicad_cli: true, skidl: true, png: true, reason: null,
};
const PCB_UNAVAILABLE: KicadPcbStatus = {
  available: false, footprints: false, symbols: false,
  reason: "footprint libraries not found",
};
const PCB_AVAILABLE: KicadPcbStatus = {
  available: true, footprints: true, symbols: true, reason: null,
};
const FAB_BOM_ONLY: FabStatus = {
  bom: true, cpl: false, gerbers: false, kicad_cli: false, footprints: false,
  reason: "kicad-cli not on PATH (needed for Gerbers)",
};
const FAB_FULL: FabStatus = {
  bom: true, cpl: true, gerbers: true, kicad_cli: true, footprints: true, reason: null,
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
  mockApi.kicadPcbStatus.mockReset();
  mockApi.kicadPcb.mockReset();
  mockApi.fabStatus.mockReset();
  mockApi.fabBom.mockReset();
  mockApi.fabCpl.mockReset();
  mockApi.fabPackage.mockReset();
  mockApi.kicadRenderStatus.mockResolvedValue(UNAVAILABLE);
  mockApi.kicadPcbStatus.mockResolvedValue(PCB_UNAVAILABLE);
  mockApi.fabStatus.mockResolvedValue(FAB_BOM_ONLY);
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

describe("SchematicDialog — PCB board", () => {
  it("shows a notice when the libraries are unavailable", async () => {
    render(<SchematicDialog design={design} onClose={() => {}} />);
    await waitFor(() => screen.getByText(/board export needs the KiCad footprint/));
    expect(screen.queryByRole("button", { name: /Download \.kicad_pcb/ })).toBeNull();
  });

  it("downloads a .kicad_pcb when the libraries are available", async () => {
    mockApi.kicadPcbStatus.mockResolvedValue(PCB_AVAILABLE);
    mockApi.kicadPcb.mockResolvedValue("(kicad_pcb)\n");
    render(<SchematicDialog design={design} onClose={() => {}} />);
    const btn = await screen.findByRole("button", { name: /Download \.kicad_pcb/ });
    await userEvent.click(btn);
    await waitFor(() => expect(mockApi.kicadPcb).toHaveBeenCalledWith(design));
    await waitFor(() => screen.getByText(/Downloaded ✓/));
  });
});

describe("SchematicDialog — fab outputs", () => {
  it("downloads the BOM (always available) and gates the Gerber package on kicad-cli", async () => {
    mockApi.fabBom.mockResolvedValue("Comment,Designator\n");
    render(<SchematicDialog design={design} onClose={() => {}} />);
    const bom = await screen.findByRole("button", { name: /BOM \.csv/ });
    await userEvent.click(bom);
    await waitFor(() => expect(mockApi.fabBom).toHaveBeenCalledWith(design));
    // With BOM-only status, the Gerber package button is disabled.
    expect(screen.getByRole("button", { name: /Fab package/ })).toBeDisabled();
  });

  it("enables the Gerber package when kicad-cli is available", async () => {
    mockApi.fabStatus.mockResolvedValue(FAB_FULL);
    mockApi.fabPackage.mockResolvedValue(new Blob(["zip"]));
    render(<SchematicDialog design={design} onClose={() => {}} />);
    const pkg = await screen.findByRole("button", { name: /Fab package/ });
    await waitFor(() => expect(pkg).toBeEnabled());
    await userEvent.click(pkg);
    await waitFor(() => expect(mockApi.fabPackage).toHaveBeenCalledWith(design));
  });
});
