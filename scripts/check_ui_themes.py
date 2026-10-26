"""Screenshot the workbench in both themes and check the design tokens apply.

Serves the built web bundle (`web/dist`) with the studio API, loads one
bundled example in a headless Chromium per theme, and fails when:

- the page raises an uncaught error or logs a console error,
- `<html data-theme>` does not follow the stored theme,
- the page background or a section heading does not resolve to the
  `surface-0` / `ink-faint` value `web/design/tokens.json` gives that theme,
- the two themes render the same background,
- at any of `WIDTHS`, with advanced mode on and an unsaved edit (the
  widest header), the page is wider than the window.

Screenshots land in `--out` (default `ui-screenshots/`) for review.

    cd web && npm ci && npm run build && cd ..
    pip install playwright && python -m playwright install chromium
    python scripts/check_ui_themes.py
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "web" / "design" / "tokens.json"
DIST = ROOT / "web" / "dist"
EXAMPLE = "Garage motion sensor"
THEMES = ("dark", "light")
WIDTHS = (1280, 1366, 1440, 1536, 1600, 1680, 1760, 1920)


def token(name: str, theme: str) -> str:
    tokens = json.loads(TOKENS.read_text())["color"]["tokens"]
    value = next(t["value"] for t in tokens if t["name"] == name)
    return value if isinstance(value, str) else value.get(theme, value["dark"])


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except OSError:
            time.sleep(0.5)
    raise SystemExit(f"studio did not answer at {url} within {timeout:.0f}s")


def resolve(page, css_color: str) -> str:
    """The browser's computed form of a CSS color, for comparison."""
    return page.evaluate(
        """(c) => { const el = document.createElement('div'); el.style.color = c;
                    document.body.appendChild(el); const v = getComputedStyle(el).color;
                    el.remove(); return v; }""",
        css_color,
    )


def check_theme(browser, base: str, theme: str, out: Path) -> list[str]:
    errors: list[str] = []
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(f"localStorage.setItem('wirestudio:ui:theme', '{theme}')")
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))

    page.goto(base)
    page.get_by_role("button", name=EXAMPLE).first.click()
    heading = page.locator("h3", has_text="Components").first
    heading.wait_for(timeout=30_000)
    page.wait_for_load_state("networkidle")

    if (got := page.evaluate("document.documentElement.dataset.theme")) != theme:
        errors.append(f"data-theme is {got!r}")
    background = page.evaluate("getComputedStyle(document.body).backgroundColor")
    if background != (want := resolve(page, token("surface-0", theme))):
        errors.append(f"body background {background} != surface-0 {want}")
    label = heading.evaluate("el => getComputedStyle(el).color")
    if label != (want := resolve(page, token("ink-faint", theme))):
        errors.append(f"section heading {label} != ink-faint {want}")

    page.screenshot(path=str(out / f"workbench-{theme}.png"), full_page=True)
    ctx.close()
    return [f"[{theme}] {e}" for e in errors] + ([] if errors else [f"[{theme}] bg {background}"])


def check_widths(browser, base: str) -> list[str]:
    failures: list[str] = []
    for width in WIDTHS:
        ctx = browser.new_context(viewport={"width": width, "height": 900})
        ctx.add_init_script("localStorage.setItem('wirestudio:ui:advanced', '1')")
        page = ctx.new_page()
        page.goto(base)
        page.get_by_role("button", name="Open an example").click()
        page.locator("h3", has_text="Components").first.wait_for(timeout=30_000)
        page.get_by_role("tab", name="Warnings").first.click()
        page.get_by_text("+ Add warning").click()
        page.get_by_text("Unsaved changes").wait_for()
        doc = page.evaluate("document.documentElement.scrollWidth")
        if doc > width:
            failures.append(f"[{width}px] page is {doc}px wide with advanced mode and unsaved changes")
        ctx.close()
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "ui-screenshots")
    args = ap.parse_args()
    if not (DIST / "index.html").is_file():
        raise SystemExit("web/dist is missing; run `npm run build` in web/ first")
    args.out.mkdir(parents=True, exist_ok=True)

    port = free_port()
    base = f"http://127.0.0.1:{port}/"
    env = {**os.environ, "WIRESTUDIO_STATIC_DIR": str(DIST)}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "wirestudio.api.serve:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=env, cwd=ROOT,
    )
    try:
        wait_for(base)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            results = [r for t in THEMES for r in check_theme(browser, base, t, args.out)]
            results += check_widths(browser, base)
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)

    backgrounds = {r.split(" bg ", 1)[1] for r in results if " bg " in r}
    failures = [r for r in results if " bg " not in r]
    if len(backgrounds) < len(THEMES) and not failures:
        failures.append("both themes render the same background")
    for f in failures:
        print(f"FAIL {f}")
    if failures:
        return 1
    print(f"OK: {', '.join(THEMES)} render with their tokens; screenshots in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
