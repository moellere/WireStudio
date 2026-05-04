/**
 * Component tests for EnclosureDialog (0.8 v2). Two surfaces:
 *
 *   Generate tab — clicks the action and confirms api.enclosureScad
 *                  was called with the live design; surface state
 *                  flips to "Downloaded ✓" on success and to a
 *                  rose error banner on a 422.
 *   Search tab   — first-open kicks off api.enclosureSearch with
 *                  library_id from props and no refinement; per-source
 *                  status banners render with reasons + configure
 *                  hints; results list renders title + creator + likes
 *                  with a link to the source.
 *
 * api/client mocked at the import boundary. URL.createObjectURL is
 * stubbed so the Generate tab's <a download> click doesn't crash
 * jsdom (which lacks the API).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { EnclosureDialog } from "./EnclosureDialog";
import { api } from "../api/client";
import type { Design, EnclosureSearchResponse } from "../types/api";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    api: {
      ...actual.api,
      enclosureScad: vi.fn(),
      enclosureSearch: vi.fn(),
      enclosureSearchStatus: vi.fn(),
    },
  };
});

const mockApi = api as unknown as {
  enclosureScad: ReturnType<typeof vi.fn>;
  enclosureSearch: ReturnType<typeof vi.fn>;
  enclosureSearchStatus: ReturnType<typeof vi.fn>;
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
  mockApi.enclosureScad.mockReset();
  mockApi.enclosureSearch.mockReset();
  mockApi.enclosureSearchStatus.mockReset();

  // jsdom lacks URL.createObjectURL/revokeObjectURL; stub them so the
  // Generate tab's <a download> click doesn't throw.
  (URL as unknown as { createObjectURL: () => string }).createObjectURL = vi.fn(() => "blob:fake");
  (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = vi.fn();
});

afterEach(() => {
  delete (URL as unknown as Record<string, unknown>).createObjectURL;
  delete (URL as unknown as Record<string, unknown>).revokeObjectURL;
});


describe("Generate tab", () => {
  it("clicks generate -> calls enclosureScad with the design and shows the success state", async () => {
    mockApi.enclosureScad.mockResolvedValue("// .scad text\nmodule shell() {}\n");
    mockApi.enclosureSearch.mockResolvedValue({
      query: "x", sources: [], results: [],
    } as EnclosureSearchResponse);
    render(
      <EnclosureDialog
        design={design}
        boardLibraryId="esp32-devkitc-v4"
        boardName="ESP32-DevKitC-V4"
        onClose={() => {}}
      />,
    );
    const btn = await screen.findByRole("button", { name: /Generate enclosure/ });
    await userEvent.click(btn);
    await waitFor(() => expect(mockApi.enclosureScad).toHaveBeenCalledWith(design));
    await waitFor(() => screen.getByText(/Downloaded ✓/));
  });

  it("surfaces a 422 from the server in a rose-toned banner", async () => {
    const { ApiError } = await vi.importActual<typeof import("../api/client")>(
      "../api/client",
    );
    mockApi.enclosureScad.mockRejectedValue(
      new ApiError(422, "POST /design/enclosure/openscad -> 422", {
        detail: "board 'esp01_1m' has no enclosure metadata",
      }),
    );
    mockApi.enclosureSearch.mockResolvedValue({
      query: "x", sources: [], results: [],
    } as EnclosureSearchResponse);
    render(
      <EnclosureDialog
        design={design}
        boardLibraryId="esp01_1m"
        boardName="ESP-01S"
        onClose={() => {}}
      />,
    );
    const btn = await screen.findByRole("button", { name: /Generate enclosure/ });
    await userEvent.click(btn);
    await waitFor(() => screen.getByText(/no enclosure metadata/));
  });
});


describe("Search tab", () => {
  it("kicks off a search with library_id on first open + renders results", async () => {
    mockApi.enclosureSearch.mockResolvedValue({
      query: "ESP32-DevKitC-V4 enclosure",
      sources: [
        { source: "thingiverse", available: true, reason: null, configure_hint: null },
        {
          source: "printables",
          available: false,
          reason: "Printables search deferred -- no public API yet",
          configure_hint: null,
        },
      ],
      results: [
        {
          source: "thingiverse",
          id: "12345",
          title: "DevKitC enclosure",
          creator: "joedirt",
          thumbnail_url: "https://example.com/t.jpg",
          model_url: "https://www.thingiverse.com/thing:12345",
          likes: 42,
          summary: null,
        },
      ],
    } as EnclosureSearchResponse);

    render(
      <EnclosureDialog
        design={design}
        boardLibraryId="esp32-devkitc-v4"
        boardName="ESP32-DevKitC-V4"
        onClose={() => {}}
      />,
    );

    // Switch to Search tab.
    await userEvent.click(screen.getByRole("button", { name: /Search community/ }));

    await waitFor(() => expect(mockApi.enclosureSearch).toHaveBeenCalledWith({
      library_id: "esp32-devkitc-v4",
      query: undefined,
    }));

    // Source statuses render. "thingiverse" appears twice (status banner +
    // result row tag), so accept any match.
    await waitFor(() => expect(screen.getAllByText(/thingiverse/).length).toBeGreaterThan(0));
    expect(screen.getByText(/· available/)).toBeInTheDocument();
    expect(screen.getByText(/Printables search deferred/)).toBeInTheDocument();

    // Result row renders with creator + likes + link.
    const link = screen.getByRole("link", { name: "DevKitC enclosure" });
    expect(link).toHaveAttribute("href", "https://www.thingiverse.com/thing:12345");
    expect(screen.getByText(/by joedirt/)).toBeInTheDocument();
    expect(screen.getByText(/♥ 42/)).toBeInTheDocument();
  });

  it("submits a refinement back to enclosureSearch when the user types + clicks Search", async () => {
    mockApi.enclosureSearch.mockResolvedValue({
      query: "ESP32-DevKitC-V4 enclosure",
      sources: [
        { source: "thingiverse", available: true, reason: null, configure_hint: null },
      ],
      results: [],
    } as EnclosureSearchResponse);

    render(
      <EnclosureDialog
        design={design}
        boardLibraryId="esp32-devkitc-v4"
        boardName="ESP32-DevKitC-V4"
        onClose={() => {}}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /Search community/ }));
    await waitFor(() => expect(mockApi.enclosureSearch).toHaveBeenCalledTimes(1));

    const refinement = screen.getByPlaceholderText(/battery, screw mount, slim/);
    await userEvent.type(refinement, "battery");
    await userEvent.click(screen.getByRole("button", { name: /^Search$/ }));

    await waitFor(() => expect(mockApi.enclosureSearch).toHaveBeenLastCalledWith({
      library_id: "esp32-devkitc-v4",
      query: "battery",
    }));
  });

  it("renders the configuration hint when no source is available", async () => {
    mockApi.enclosureSearch.mockResolvedValue({
      query: "ESP32-DevKitC-V4 enclosure",
      sources: [
        {
          source: "thingiverse",
          available: false,
          reason: "THINGIVERSE_API_KEY not set",
          configure_hint:
            "Register an app at https://www.thingiverse.com/developers and export THINGIVERSE_API_KEY=<token>",
        },
        {
          source: "printables",
          available: false,
          reason: "Printables search deferred -- no public API yet",
          configure_hint: null,
        },
      ],
      results: [],
    } as EnclosureSearchResponse);

    render(
      <EnclosureDialog
        design={design}
        boardLibraryId="esp32-devkitc-v4"
        boardName="ESP32-DevKitC-V4"
        onClose={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Search community/ }));
    // THINGIVERSE_API_KEY appears twice: in the reason banner and in the
    // configure_hint subline. Either is fine.
    await waitFor(() => expect(screen.getAllByText(/THINGIVERSE_API_KEY/).length).toBeGreaterThan(0));
    expect(screen.getByText(/thingiverse.com\/developers/)).toBeInTheDocument();
    expect(screen.getByText(/No search source is configured/i)).toBeInTheDocument();
  });
});
