import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FeedbackLink, issueUrl } from "./FeedbackLink";

describe("issueUrl", () => {
  it("points at the repo's new-issue form", () => {
    expect(issueUrl("0.25.1")).toContain(
      "https://github.com/moellere/WireStudio/issues/new",
    );
  });

  it("prefills version and board so the reporter isn't asked for them", () => {
    const body = decodeURIComponent(issueUrl("0.25.1", "ttgo-t-beam").split("body=")[1]);
    expect(body).toContain("wirestudio v0.25.1");
    expect(body).toContain("board: ttgo-t-beam");
  });

  it("still works before /api/health has answered", () => {
    const body = decodeURIComponent(issueUrl(null).split("body=")[1]);
    expect(body).toContain("version unknown");
    expect(body).not.toContain("board:");
  });

  it("encodes the body, so newlines can't truncate the URL", () => {
    const url = issueUrl("0.25.1", "esp32-devkitc-v4");
    expect(url).not.toContain("\n");
    expect(url).toContain("%0A");
  });
});

describe("FeedbackLink", () => {
  it("opens in a new tab without handing the opener to GitHub", () => {
    render(<FeedbackLink version="0.25.1" />);
    const link = screen.getByRole("link", { name: /send feedback/i });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });
});
