import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { LeftSidebar, type CommunityList } from "./LeftSidebar";
import type { CommunityEntry } from "../types/api";

const ENTRY: CommunityEntry = {
  slug: "porch-motion", name: "Porch motion", description: "PIR + BME280", author: "octocat",
  tags: ["motion", "outdoor"], license: "CC-BY-4.0", derived_from: null, source: null,
  board: "esp32-devkitc-v4", mcu: "esp32", components: ["bme280", "hc-sr501"], updated: null,
  page_url: "https://github.com/moellere/wirestudio-designs/tree/main/designs/porch-motion",
};

function sidebar(community: CommunityList | null, onSelectCommunity = vi.fn()) {
  const noop = () => {};
  render(
    <LeftSidebar
      examples={[]} saved={[]} boards={[]} components={[]} modules={[]}
      community={community} selectedExample={null} selectedCommunity={null} selectedSaved={null}
      onSelectExample={noop} onSelectCommunity={onSelectCommunity} onSelectSaved={noop}
      onDeleteSaved={noop} onSelectBoard={noop} onSelectComponent={noop}
      onNewComponent={noop} onInsertModule={noop}
    />,
  );
  return onSelectCommunity;
}

describe("LeftSidebar community gallery", () => {
  it("has no gallery tab when the catalogue is off", () => {
    sidebar(null);
    expect(screen.queryByTitle("Community designs")).toBeNull();
  });

  it("lists designs with their author and filters on tags", async () => {
    const onSelect = sidebar({ items: [ENTRY], error: null });
    await userEvent.click(screen.getByTitle("Community designs"));
    expect(screen.getByText("@octocat")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("searchbox"), "outdoor");
    await userEvent.click(screen.getByText("Porch motion"));
    expect(onSelect).toHaveBeenCalledWith("porch-motion");
    await userEvent.clear(screen.getByRole("searchbox"));
    await userEvent.type(screen.getByRole("searchbox"), "nomatch");
    expect(screen.getByText(/no community designs match/i)).toBeInTheDocument();
  });

  it("shows the first merged photo as a thumbnail", async () => {
    const photo = "https://raw.githubusercontent.com/moellere/wirestudio-designs/main/designs/porch-motion/photos/front.jpg";
    sidebar({ items: [{ ...ENTRY, photos: [photo] }], error: null });
    await userEvent.click(screen.getByTitle("Community designs"));
    expect(document.querySelector(`img[src="${photo}"]`)).not.toBeNull();
  });

  it("badges a design that runs custom code", async () => {
    sidebar({ items: [{ ...ENTRY, custom_code: ["lambda"] }], error: null });
    await userEvent.click(screen.getByTitle("Community designs"));
    expect(screen.getByText("custom code")).toHaveAttribute("title", expect.stringContaining("lambda"));
  });

  it("says why the catalogue is unavailable", async () => {
    sidebar({ items: null, error: "502: catalogue index unavailable" });
    await userEvent.click(screen.getByTitle("Community designs"));
    expect(screen.getByText(/catalogue index unavailable/)).toBeInTheDocument();
  });
});
