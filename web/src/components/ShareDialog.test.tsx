import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ShareDialog, parseTags } from "./ShareDialog";
import { api, ApiError } from "../api/client";
import type { CommunityStatus } from "../types/api";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, api: { ...actual.api, communityShare: vi.fn() } };
});

const STATUS: CommunityStatus = {
  enabled: true,
  repo: "moellere/wirestudio-designs",
  license: "CC-BY-4.0",
  upload_url: "https://github.com/moellere/wirestudio-designs/upload/main/designs",
  contributing_url: "https://github.com/moellere/wirestudio-designs/blob/main/CONTRIBUTING.md",
};
const share = api.communityShare as unknown as ReturnType<typeof vi.fn>;

describe("ShareDialog", () => {
  beforeEach(() => {
    share.mockReset();
    localStorage.clear();
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
  });

  it("normalises tags", () => {
    expect(parseTags(" Climate, oled  climate,,battery ")).toEqual(["climate", "oled", "battery"]);
  });

  it("packs the design, opens the upload page and remembers the handle", async () => {
    share.mockResolvedValue(new Blob(["zip"]));
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<ShareDialog design={{ id: "porch" }} status={STATUS} onClose={() => {}} />);

    await userEvent.type(screen.getByPlaceholderText("octocat"), "@me");
    await userEvent.type(screen.getByPlaceholderText(/climate/), "motion, PIR");
    await userEvent.click(screen.getByRole("button", { name: /download and open github/i }));

    await waitFor(() => expect(open).toHaveBeenCalledWith(STATUS.upload_url, "_blank", "noopener"));
    expect(share.mock.calls[0][0]).toEqual({ design: { id: "porch" }, author: "me", tags: ["motion", "pir"], notes: "", photos: [] });
    expect(localStorage.getItem("wirestudio.githubHandle")).toBe("me");
    expect(screen.getByText(/drag that folder/i)).toBeInTheDocument();
  });

  it("sends attached photos as base64, at most four", async () => {
    share.mockResolvedValue(new Blob(["zip"]));
    vi.spyOn(window, "open").mockReturnValue(null);
    render(<ShareDialog design={{ id: "porch" }} status={STATUS} onClose={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText("octocat"), "me");
    const files = Array.from({ length: 5 }, (_, i) => new File([new Uint8Array([1, 2, 3])], `p${i}.jpg`, { type: "image/jpeg" }));
    await userEvent.upload(screen.getByLabelText("Photos of the build"), files);
    await userEvent.click(screen.getByRole("button", { name: /download and open github/i }));
    await waitFor(() => expect(share).toHaveBeenCalled());
    const sent = share.mock.calls[0][0].photos;
    expect(sent).toHaveLength(4);
    expect(sent[0]).toEqual({ name: "p0.jpg", data: "AQID" });
  });

  it("shows why the studio refused to share", async () => {
    share.mockRejectedValue(new ApiError(422, "literal credentials at fleet.secrets_ref.wifi_password", undefined));
    render(<ShareDialog design={{ id: "porch" }} status={STATUS} onClose={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText("octocat"), "me");
    await userEvent.click(screen.getByRole("button", { name: /download and open github/i }));
    expect(await screen.findByText(/literal credentials/)).toBeInTheDocument();
  });

  it("names the design it was imported from", () => {
    const design = { id: "porch-v2", origin: { catalogue: STATUS.repo, slug: "porch", author: "someone", license: "CC-BY-4.0" } };
    render(<ShareDialog design={design} status={STATUS} onClose={() => {}} />);
    expect(screen.getByText(/@someone/)).toBeInTheDocument();
  });
});
