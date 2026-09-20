import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ComponentEditorDialog, NEW_COMPONENT_TEMPLATE } from "./ComponentEditorDialog";
import type { ComponentCheckResponse } from "../types/api";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    api: {
      checkComponentYaml: vi.fn(),
      createComponent: vi.fn(),
    },
  };
});

import { ApiError, api } from "../api/client";

const clean: ComponentCheckResponse = {
  ok: true, library_id: "my_component", exists: "", errors: [], warnings: ["pin role 'GND' is not connected to any subcircuit part"],
  unverified: ["KiCad symbols not checked: no symbol library found (set KICAD8_SYMBOL_DIR)"],
  not_checked: ["electrical behaviour: nothing is simulated"], verified: [], saved: "",
};

describe("ComponentEditorDialog", () => {
  beforeEach(() => vi.clearAllMocks());

  it("checks the YAML and shows every report section", async () => {
    vi.mocked(api.checkComponentYaml).mockResolvedValue(clean);
    render(<ComponentEditorDialog title="New component" initialYaml={NEW_COMPONENT_TEMPLATE} overwrite={false} onClose={vi.fn()} onSaved={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    await waitFor(() => expect(screen.getByText("my_component: passes")).toBeInTheDocument());
    expect(api.checkComponentYaml).toHaveBeenCalledWith(NEW_COMPONENT_TEMPLATE);
    expect(screen.getByText(/pin role 'GND'/)).toBeInTheDocument();
    expect(screen.getByText(/KiCad symbols not checked/)).toBeInTheDocument();
    expect(screen.getByText(/nothing is simulated/)).toBeInTheDocument();
  });

  it("creates on save and reports the saved path", async () => {
    const onSaved = vi.fn();
    vi.mocked(api.createComponent).mockResolvedValue({ ...clean, saved: "/data/library/components/my_component.yaml" });
    render(<ComponentEditorDialog title="New component" initialYaml="id: my_component" overwrite={false} onClose={vi.fn()} onSaved={onSaved} />);
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("my_component"));
    expect(api.createComponent).toHaveBeenCalledWith("id: my_component", false);
  });

  it("shows the report from a rejected save instead of a bare error", async () => {
    const onSaved = vi.fn();
    vi.mocked(api.createComponent).mockRejectedValue(new ApiError(422, "Unprocessable", {
      ...clean, ok: false, errors: ["esphome.yaml_template line 3: unexpected '}'"],
    }));
    render(<ComponentEditorDialog title="Edit x" initialYaml="id: x" overwrite={true} onClose={vi.fn()} onSaved={onSaved} />);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByText(/unexpected '}'/)).toBeInTheDocument());
    expect(onSaved).not.toHaveBeenCalled();
    expect(api.createComponent).toHaveBeenCalledWith("id: x", true);
  });
});
