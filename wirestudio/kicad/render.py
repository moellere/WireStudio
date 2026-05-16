"""Render a design's schematic to an image via SKiDL + kicad-cli.

Pipeline: design -> SKiDL script (`generate_skidl`) -> run the script in a
subprocess (produces a `.kicad_sch`) -> `kicad-cli sch export svg` -> SVG.
`--png` rasterizes the SVG with whatever converter is on the system.

SKiDL is never imported into wirestudio's process -- the generated script
is run as a subprocess with `sys.executable`, the same way a user would
run it by hand. That keeps numpy + the EDA-toolchain weight out of the
import graph (see `wirestudio/kicad/generator.py`). The whole feature is
optional: `render_status()` probes for the tools, and the API / web UI
gate the preview on it the same way the agent and fleet features gate on
their own config.

CLI: `python -m wirestudio.kicad.render <design.json> [-o out.svg] [--png]`.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from wirestudio.kicad.generator import generate_skidl
from wirestudio.library import Library, default_library
from wirestudio.model import Design

_TIMEOUT = 120  # seconds, per subprocess -- SKiDL and kicad-cli are both slow


class RenderUnavailable(RuntimeError):
    """A required tool (kicad-cli / skidl / a PNG converter) is not installed."""


class RenderError(RuntimeError):
    """The render pipeline ran but a step failed (nonzero exit / no output)."""


def _skidl_importable() -> bool:
    return importlib.util.find_spec("skidl") is not None


def _png_converter() -> str | None:
    """Name of the first available SVG->PNG converter, or None.

    cairosvg (a pure-Python lib) is preferred for determinism; the
    command-line rasterizers are fallbacks."""
    if importlib.util.find_spec("cairosvg") is not None:
        return "cairosvg"
    for exe in ("rsvg-convert", "magick", "convert"):
        if shutil.which(exe) is not None:
            return exe
    return None


def render_status() -> dict:
    """Probe for the tools the render pipeline needs.

    Shape mirrors the other feature-gate status endpoints: `available`
    is the headline the UI keys off, the rest explains what's missing."""
    kicad_cli = shutil.which("kicad-cli") is not None
    skidl = _skidl_importable()
    png = _png_converter() is not None
    available = kicad_cli and skidl
    reason = None
    if not available:
        missing = []
        if not kicad_cli:
            missing.append("kicad-cli not on PATH")
        if not skidl:
            missing.append(f"skidl not importable by {sys.executable}")
        reason = "; ".join(missing)
    return {
        "available": available,
        "kicad_cli": kicad_cli,
        "skidl": skidl,
        "png": png,
        "reason": reason,
    }


def render_schematic(design: Design, library: Library, *, fmt: str = "svg") -> bytes:
    """Render `design`'s schematic to SVG (or PNG) bytes.

    Raises `RenderUnavailable` when a required tool is missing and
    `RenderError` when a pipeline step fails.
    """
    if fmt not in ("svg", "png"):
        raise ValueError(f"fmt must be 'svg' or 'png', got {fmt!r}")

    status = render_status()
    if not status["kicad_cli"]:
        raise RenderUnavailable("kicad-cli not found on PATH")
    if not status["skidl"]:
        raise RenderUnavailable(f"skidl not importable by {sys.executable}")
    if fmt == "png" and not status["png"]:
        raise RenderUnavailable(
            "no SVG->PNG converter found (install cairosvg, rsvg-convert, "
            "or ImageMagick)"
        )

    script = generate_skidl(design, library)

    with tempfile.TemporaryDirectory(prefix="wirestudio-render-") as td:
        tmp = Path(td)
        (tmp / "schematic.py").write_text(script)

        skidl_run = subprocess.run(
            [sys.executable, "schematic.py"],
            cwd=td,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if skidl_run.returncode != 0:
            raise RenderError(
                "SKiDL script failed:\n" + (skidl_run.stderr or "")[-2000:]
            )

        sch = sorted(tmp.glob("*.kicad_sch"))
        if not sch:
            raise RenderError("SKiDL produced no .kicad_sch file")

        out_dir = tmp / "out"
        out_dir.mkdir()
        cli_run = subprocess.run(
            ["kicad-cli", "sch", "export", "svg", "--output", str(out_dir), str(sch[0])],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if cli_run.returncode != 0:
            raise RenderError("kicad-cli failed:\n" + (cli_run.stderr or "")[-2000:])

        svgs = sorted(out_dir.glob("*.svg")) or sorted(tmp.glob("*.svg"))
        if not svgs:
            raise RenderError("kicad-cli produced no SVG output")
        svg_bytes = svgs[0].read_bytes()

    if fmt == "svg":
        return svg_bytes
    return _svg_to_png(svg_bytes)


def _svg_to_png(svg: bytes) -> bytes:
    conv = _png_converter()
    if conv is None:
        raise RenderUnavailable("no SVG->PNG converter available")
    if conv == "cairosvg":
        import cairosvg

        return cairosvg.svg2png(bytestring=svg)
    cmd = ["rsvg-convert", "-f", "png"] if conv == "rsvg-convert" else [conv, "svg:-", "png:-"]
    proc = subprocess.run(cmd, input=svg, capture_output=True, timeout=_TIMEOUT)
    if proc.returncode != 0:
        raise RenderError(
            f"{conv} failed: " + proc.stderr.decode("utf-8", "replace")[-1000:]
        )
    return proc.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wirestudio.kicad.render",
        description="Render a design's KiCad schematic to SVG or PNG.",
    )
    parser.add_argument("design", nargs="?", help="path to a design.json")
    parser.add_argument("-o", "--out", help="output file (default: <design id>.<fmt>)")
    parser.add_argument("--png", action="store_true", help="rasterize the SVG to PNG")
    parser.add_argument(
        "--status", action="store_true",
        help="print tool availability as JSON and exit",
    )
    args = parser.parse_args(argv)

    if args.status:
        print(json.dumps(render_status(), indent=2))
        return 0
    if not args.design:
        parser.error("a design.json path is required (or pass --status)")

    design = Design.model_validate(json.loads(Path(args.design).read_text()))
    fmt = "png" if args.png else "svg"
    try:
        data = render_schematic(design, default_library(), fmt=fmt)
    except RenderUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("run with --status to see what's missing", file=sys.stderr)
        return 2
    except RenderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = Path(args.out) if args.out else Path(f"{design.id}.{fmt}")
    out.write_bytes(data)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
