"""Render a design's schematic to an image via kicad-cli.

Pipeline: design -> `.kicad_sch` (`wirestudio.kicad.schematic`, in
process) -> `kicad-cli sch export svg` -> SVG. `--png` rasterizes the
SVG with whatever converter is on the system.

The sheet writer needs the pinned KiCad symbol libraries to embed the
symbols, so the feature gates on those plus kicad-cli: `render_status()`
probes for both, and the API / web UI gate the preview on it the same
way the agent and fleet features gate on their own config.

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

from wirestudio.kicad.pcb import generate_kicad_pcb, pcb_status
from wirestudio.kicad.schematic import SchematicUnavailable, generate_kicad_sch, sch_status
from wirestudio.library import Library, default_library
from wirestudio.migrate import load_design
from wirestudio.model import Design

_TIMEOUT = 120  # seconds, per subprocess -- kicad-cli is slow to start


class RenderUnavailable(RuntimeError):
    """A required tool (kicad-cli / symbol libraries / a PNG converter) is not installed."""


class RenderError(RuntimeError):
    """The render pipeline ran but a step failed (nonzero exit / no output)."""


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
    symbols = sch_status()
    png = _png_converter() is not None
    available = kicad_cli and symbols["available"]
    reason = None
    if not available:
        missing = []
        if not kicad_cli:
            missing.append("kicad-cli not on PATH")
        if not symbols["available"]:
            missing.append(symbols["reason"])
        reason = "; ".join(missing)
    return {
        "available": available,
        "kicad_cli": kicad_cli,
        "symbols": symbols["available"],
        "png": png,
        "reason": reason,
    }


def write_schematic(design: Design, library: Library, directory: Path) -> Path:
    """The design's `.kicad_sch` in `directory`. Raises RenderUnavailable
    without the symbol libraries, FileNotFoundError for a symbol the
    library lacks."""
    try:
        text = generate_kicad_sch(design, library)
    except SchematicUnavailable as e:
        raise RenderUnavailable(str(e)) from e
    path = directory / f"{design.id}.kicad_sch"
    path.write_text(text)
    return path


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
    if not status["symbols"]:
        raise RenderUnavailable(sch_status()["reason"])
    if fmt == "png" and not status["png"]:
        raise RenderUnavailable(
            "no SVG->PNG converter found (install cairosvg, rsvg-convert, "
            "or ImageMagick)"
        )

    with tempfile.TemporaryDirectory(prefix="wirestudio-render-") as td:
        tmp = Path(td)
        sch = write_schematic(design, library, tmp)
        out_dir = tmp / "out"
        out_dir.mkdir()
        cli_run = subprocess.run(
            ["kicad-cli", "sch", "export", "svg", "--output", str(out_dir), str(sch)],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if cli_run.returncode != 0:
            raise RenderError(
                "kicad-cli failed:\n"
                + ((cli_run.stdout or "") + (cli_run.stderr or ""))[-2000:]
            )

        svgs = sorted(out_dir.glob("*.svg")) or sorted(tmp.glob("*.svg"))
        if not svgs:
            raise RenderError("kicad-cli produced no SVG output")
        svg_bytes = svgs[0].read_bytes()

    if fmt == "svg":
        return svg_bytes
    return _svg_to_png(svg_bytes)


_PCB_LAYERS = "F.Cu,B.Cu,F.SilkS,Edge.Cuts"


def pcb_render_status() -> dict:
    """Probe for the tools the PCB preview needs: kicad-cli for the SVG
    export plus the footprint/symbol libraries the board generator embeds."""
    kicad_cli = shutil.which("kicad-cli") is not None
    libs = pcb_status()
    available = kicad_cli and libs["available"]
    reason = None
    if not available:
        missing = []
        if not kicad_cli:
            missing.append("kicad-cli not on PATH")
        if libs["reason"]:
            missing.append(libs["reason"])
        reason = "; ".join(missing)
    return {
        "available": available,
        "kicad_cli": kicad_cli,
        "libraries": libs["available"],
        "reason": reason,
    }


def render_pcb(design: Design, library: Library) -> bytes:
    """Render the design's placed (unrouted) board to SVG bytes.

    Raises `RenderUnavailable` when kicad-cli or the KiCad libraries are
    missing and `RenderError` when the export fails.
    """
    status = pcb_render_status()
    if not status["available"]:
        raise RenderUnavailable(status["reason"])

    board_text = generate_kicad_pcb(design, library)

    with tempfile.TemporaryDirectory(prefix="wirestudio-render-") as td:
        tmp = Path(td)
        board = tmp / "board.kicad_pcb"
        board.write_text(board_text)
        out = tmp / "board.svg"
        cli_run = subprocess.run(
            [
                "kicad-cli", "pcb", "export", "svg",
                "--output", str(out),
                "--layers", _PCB_LAYERS,
                "--page-size-mode", "2",
                "--exclude-drawing-sheet",
                str(board),
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if cli_run.returncode != 0:
            raise RenderError(
                "kicad-cli failed:\n"
                + ((cli_run.stdout or "") + (cli_run.stderr or ""))[-2000:]
            )
        if not out.exists():
            raise RenderError("kicad-cli produced no SVG output")
        return out.read_bytes()


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

    design = load_design(json.loads(Path(args.design).read_text()))
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
