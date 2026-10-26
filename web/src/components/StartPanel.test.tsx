import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StartPanel } from "./StartPanel";
import type { SavedDesignSummary } from "../types/api";

function saved(id: string, saved_at: string): SavedDesignSummary {
  return {
    id, name: id, description: "", board_library_id: "esp32-devkitc-v4",
    mcu: "esp32", saved_at, component_count: 1,
  };
}

function setup(over: Partial<Parameters<typeof StartPanel>[0]> = {}) {
  const props = {
    exampleCount: 42, boardCount: 26, saved: null, error: null,
    onOpenExample: vi.fn(), onNewFromBoard: vi.fn(), onConnectDevice: vi.fn(), onOpenSaved: vi.fn(),
    ...over,
  };
  render(<StartPanel {...props} />);
  return props;
}

describe("StartPanel", () => {
  it("routes each start card to its action", () => {
    const p = setup();
    fireEvent.click(screen.getByRole("button", { name: /Open an example/ }));
    fireEvent.click(screen.getByRole("button", { name: /New from a board/ }));
    fireEvent.click(screen.getByRole("button", { name: /Connect a device/ }));
    expect(p.onOpenExample).toHaveBeenCalledOnce();
    expect(p.onNewFromBoard).toHaveBeenCalledOnce();
    expect(p.onConnectDevice).toHaveBeenCalledOnce();
    expect(screen.getByText("42 examples")).toBeInTheDocument();
  });

  it("lists the four most recent saved designs, newest first", () => {
    const p = setup({
      saved: [
        saved("a", "2026-10-01T00:00:00Z"), saved("b", "2026-10-05T00:00:00Z"),
        saved("c", "2026-10-03T00:00:00Z"), saved("d", "2026-10-04T00:00:00Z"),
        saved("e", "2026-10-02T00:00:00Z"),
      ],
    });
    const names = screen.getAllByRole("listitem").map((li) => li.querySelector(".font-medium")?.textContent);
    expect(names).toEqual(["b", "d", "c", "e"]);
    fireEvent.click(screen.getAllByRole("listitem")[0].querySelector("button")!);
    expect(p.onOpenSaved).toHaveBeenCalledWith("b");
  });

  it("hides Recent when nothing is saved and shows a load error", () => {
    setup({ error: "404: Unknown example 'x'" });
    expect(screen.queryByText("Recent")).not.toBeInTheDocument();
    expect(screen.getByText("Could not open that design")).toBeInTheDocument();
  });
});
