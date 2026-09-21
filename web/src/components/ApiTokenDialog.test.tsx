import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiTokenDialog } from "./ApiTokenDialog";
import { getApiToken, setApiToken } from "../api/client";

describe("ApiTokenDialog", () => {
  beforeEach(() => {
    setApiToken("");
  });

  it("stores the pasted token in the browser and reports back", async () => {
    const onSaved = vi.fn();
    render(<ApiTokenDialog onSaved={onSaved} onClose={() => {}} />);
    const button = screen.getByRole("button", { name: /use this token/i });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByPlaceholderText(/paste the token/i), "  s3cret  ");
    expect(button).toBeEnabled();
    await userEvent.click(button);
    expect(onSaved).toHaveBeenCalledOnce();
    expect(getApiToken()).toBe("s3cret");
    expect(document.cookie).toContain("wirestudio_api_token=s3cret");
  });

  it("enter submits and clearing removes the cookie", async () => {
    const onSaved = vi.fn();
    render(<ApiTokenDialog onSaved={onSaved} onClose={() => {}} />);
    await userEvent.type(screen.getByPlaceholderText(/paste the token/i), "abc{Enter}");
    expect(onSaved).toHaveBeenCalledOnce();
    setApiToken("");
    expect(getApiToken()).toBe("");
    expect(document.cookie).not.toContain("wirestudio_api_token=abc");
  });
});
