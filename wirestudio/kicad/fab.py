"""Fab-output export: JLCPCB CPL + BOM, and Gerber/drill via kicad-cli.

CPL (pick-and-place) and BOM are pure functions of ``design.json`` + the
library; CPL reuses the board's placement plan so positions match exactly.
Gerber + drill need ``kicad-cli`` and are gated the same way the schematic
render is. ``export_fab_package`` zips Gerbers + drill + CPL + BOM into the
JLCPCB upload bundle.

The boards are unrouted until the Freerouting step lands, so Gerbers carry
pads but no copper traces -- ``routing_status`` flags that so a caller can warn
before someone sends an unroutable board to a fab.
"""
from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from wirestudio.kicad.netlist import BOARD_KEY, assign_refs
from wirestudio.kicad.pcb import (
    PcbUnavailable,
    _resolve_footprint_dir,
    generate_kicad_pcb,
    pcb_status,
    plan_placements,
)
from wirestudio.library import Library
from wirestudio.model import Design

_TIMEOUT = 180  # seconds per kicad-cli call


class GerberUnavailable(RuntimeError):
    """kicad-cli (or the libraries) needed for Gerber export isn't available."""


def _kicad_cli() -> Optional[str]:
    return shutil.which("kicad-cli")


def is_routed(board_text: str) -> bool:
    """True once a board carries copper traces (track segments or vias). The
    emitter produces a placed but unrouted board, so this is False until
    routing lands. Word-boundaried so footprint keepout settings like
    ``(vias not_allowed)`` don't count as routing."""
    return bool(re.search(r"\((?:segment|via)\b", board_text))


def fab_status(*, footprint_dir: Optional[Path] = None) -> dict:
    """What fab outputs are available here. BOM is always pure; CPL needs the
    footprint libraries (for placement); Gerbers also need kicad-cli; routed
    Gerbers additionally need the Freerouting toolchain."""
    from wirestudio.kicad.route import route_status

    fp = Path(footprint_dir) if footprint_dir else _resolve_footprint_dir()
    cli = _kicad_cli()
    route = route_status()
    reason = None
    if fp is None or cli is None:
        missing = []
        if fp is None:
            missing.append("footprint libraries not found (set KICAD8_FOOTPRINT_DIR)")
        if cli is None:
            missing.append("kicad-cli not on PATH (needed for Gerbers)")
        reason = "; ".join(missing)
    return {
        "bom": True,
        "cpl": fp is not None,
        "gerbers": fp is not None and cli is not None,
        "route": fp is not None and cli is not None and route["available"],
        "route_reason": route["reason"],
        "kicad_cli": cli is not None,
        "footprints": fp is not None,
        "reason": reason,
    }


def generate_cpl(design: Design, library: Library, *,
                 footprint_dir: Optional[Path] = None) -> str:
    """JLCPCB CPL (pick-and-place) CSV. Positions come from the board's
    placement plan, so they match the .kicad_pcb. Needs the footprint
    libraries (placement measures footprint extents)."""
    fp_dir = Path(footprint_dir) if footprint_dir else _resolve_footprint_dir()
    if fp_dir is None:
        raise PcbUnavailable(pcb_status()["reason"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
    for p in plan_placements(design, library, fp_dir):
        w.writerow([p.ref, f"{p.cx:.3f}", f"{p.cy:.3f}", "top", "0"])
    return buf.getvalue()


def generate_bom(design: Design, library: Library) -> str:
    """JLCPCB BOM CSV, grouped by part (value + footprint). The JLCPCB/LCSC
    part column is left blank for the user to fill. Pure."""
    refs = assign_refs(design, library)
    groups: dict[tuple[str, str], list[str]] = {}
    try:
        board = library.board(design.board.library_id)
    except FileNotFoundError:
        board = None
    if board is not None and board.kicad is not None:
        key = (board.kicad.value or board.name or board.id, board.kicad.footprint or "")
        groups.setdefault(key, []).append(refs[BOARD_KEY])
    for c in design.components:
        lib_comp = library.component(c.library_id)
        if lib_comp.kicad is None:
            continue
        comment = lib_comp.kicad.value or lib_comp.name or c.library_id
        key = (comment, lib_comp.kicad.footprint or "")
        groups.setdefault(key, []).append(refs[c.id])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Comment", "Designator", "Footprint", "JLCPCB Part #"])
    for (comment, footprint), desigs in sorted(groups.items()):
        w.writerow([comment, ",".join(sorted(desigs)), footprint, ""])
    return buf.getvalue()


def _gerbers_into(out_dir: Path, board_text: str) -> None:
    """Run kicad-cli gerbers + drill export for ``board_text`` into ``out_dir``.
    Raises GerberUnavailable on a missing tool or a failed step."""
    if _kicad_cli() is None:
        raise GerberUnavailable("kicad-cli not found on PATH")
    with tempfile.TemporaryDirectory(prefix="wirestudio-gerber-") as td:
        board = Path(td) / "board.kicad_pcb"
        board.write_text(board_text)
        for sub in ("gerbers", "drill"):
            proc = subprocess.run(
                ["kicad-cli", "pcb", "export", sub, "--output", f"{out_dir}/", str(board)],
                capture_output=True, text=True, timeout=_TIMEOUT,
            )
            if proc.returncode != 0:
                raise GerberUnavailable(
                    f"kicad-cli pcb export {sub} failed: {(proc.stderr or proc.stdout or '')[-500:]}"
                )


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def _maybe_route(board: str, route: bool) -> str:
    if not route:
        return board
    from wirestudio.kicad.route import route_board

    return route_board(board)


def export_gerbers(design: Design, library: Library, *,
                   footprint_dir: Optional[Path] = None,
                   symbol_dir: Optional[Path] = None,
                   route: bool = False) -> bytes:
    """Zip of Gerber + drill files. Needs kicad-cli + the libraries; with
    ``route=True`` the board is autorouted first (Freerouting toolchain)."""
    board = _maybe_route(generate_kicad_pcb(
        design, library, footprint_dir=footprint_dir, symbol_dir=symbol_dir,
    ), route)
    with tempfile.TemporaryDirectory(prefix="wirestudio-fab-") as td:
        out = Path(td)
        _gerbers_into(out, board)
        return _zip({f.name: f.read_bytes() for f in sorted(out.iterdir())})


def export_fab_package(design: Design, library: Library, *,
                       footprint_dir: Optional[Path] = None,
                       symbol_dir: Optional[Path] = None,
                       route: bool = False) -> bytes:
    """The JLCPCB upload bundle: Gerbers + drill + CPL + BOM in one zip."""
    board = _maybe_route(generate_kicad_pcb(
        design, library, footprint_dir=footprint_dir, symbol_dir=symbol_dir,
    ), route)
    with tempfile.TemporaryDirectory(prefix="wirestudio-fab-") as td:
        out = Path(td)
        _gerbers_into(out, board)
        files = {f.name: f.read_bytes() for f in sorted(out.iterdir())}
    files[f"{design.id}-cpl.csv"] = generate_cpl(
        design, library, footprint_dir=footprint_dir,
    ).encode()
    files[f"{design.id}-bom.csv"] = generate_bom(design, library).encode()
    return _zip(files)
