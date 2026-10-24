import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { LibraryShareDialog } from "./LibraryShareDialog";
import { api, ApiError } from "../api/client";
import type { CommunityStatus } from "../types/api";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { ...actual.api, communityShareLibrary: vi.fn() } };
});

const STATUS: CommunityStatus = {
  enabled: true,
  repo: "moellere/wirestudio-designs",
  license: "CC-BY-4.0",
  library_license: "MIT",
  library_upload_url: "https://github.com/moellere/wirestudio-designs/upload/main/library",
  contributing_url: "https://github.com/moellere/wirestudio-designs/blob/main/CONTRIBUTING.md",
};
const share = api.communityShareLibrary as unknown as ReturnType<typeof vi.fn>;

describe("LibraryShareDialog", () => {
  beforeEach(() => {
    share.mockReset();
    localStorage.clear();
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
  });

  it("packs the board and opens the library upload page for its kind", async () => {
    share.mockResolvedValue(new Blob(["zip"]));
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<LibraryShareDialog kind="boards" id="lolin-s2-mini" status={STATUS} onClose={() => {}} />);
    expect(screen.getByText(/are MIT/)).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("octocat"), "@me");
    await userEvent.type(screen.getByPlaceholderText("esp32s2, usb-c"), "ESP32S2 usb-c");
    await userEvent.type(screen.getByPlaceholderText("https://..."), "https://www.wemos.cc/s2");
    await userEvent.click(screen.getByRole("button", { name: /download and open github/i }));

    await waitFor(() => expect(open).toHaveBeenCalledWith(
      "https://github.com/moellere/wirestudio-designs/upload/main/library/boards", "_blank", "noopener"));
    expect(share).toHaveBeenCalledWith({
      kind: "boards", id: "lolin-s2-mini", author: "me", tags: ["esp32s2", "usb-c"],
      source: "https://www.wemos.cc/s2", notes: "",
    });
    expect(screen.getByText(/runs the same board gate/)).toBeInTheDocument();
    expect(localStorage.getItem("wirestudio.githubHandle")).toBe("me");
  });

  it("shows why the studio refused", async () => {
    share.mockRejectedValue(new ApiError(422, "'x' no longer passes its gate: pin missing"));
    render(<LibraryShareDialog kind="components" id="x" status={STATUS} onClose={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText("octocat"), "me");
    await userEvent.click(screen.getByRole("button", { name: /download and open github/i }));
    expect(await screen.findByText(/no longer passes its gate/)).toBeInTheDocument();
  });
});
