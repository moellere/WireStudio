"""Verify every board's parametric enclosure renders to a valid solid.

The third correctness gate, alongside `check_examples.py` (ESPHome YAML)
and `check_schematics.py` (KiCad netlist). The OpenSCAD enclosure
generator (`wirestudio.enclosure.generate_scad`) is board-driven -- the
shell geometry comes from the board's `enclosure:` block, not the
design's components -- so this walks every board that carries enclosure
metadata, renders its `.scad` through real OpenSCAD, and checks the
result is a non-empty manifold solid.

OpenSCAD's Manifold backend errors on non-manifold geometry, so a clean
render to a triangle-bearing STL is the bar: it proves the generated
shell is a closed, printable solid, not just text that parses.

Requires the `openscad` CLI. In CI the workflow apt-installs it.

Run locally:
    sudo apt-get install -y openscad   # or your platform's package
    python scripts/check_enclosures.py              # all enclosure boards
    python scripts/check_enclosures.py wemos-d1-mini

Exit code 0 = every enclosure rendered, 1 = at least one failed,
2 = openscad missing.
"""
from __future__ import annotations

import argparse
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from wirestudio.enclosure import EnclosureUnavailable, generate_scad
from wirestudio.library import default_library
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent


def _minimal_design(board_id: str, mcu: str) -> Design:
    """A schema-valid design that references a board, enough for the
    board-driven enclosure generator. Components are irrelevant to the
    shell geometry."""
    return Design.model_validate({
        "schema_version": "0.1",
        "id": f"encl-{board_id}",
        "name": f"Enclosure check for {board_id}",
        "board": {"library_id": board_id, "mcu": mcu},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0},
        "components": [],
        "buses": [],
        "connections": [],
        "requirements": [],
        "warnings": [],
    })


def _stl_triangle_count(path: Path) -> int:
    data = path.read_bytes()
    if data[:5] == b"solid" and b"facet" in data[:4096]:
        return data.count(b"facet normal")
    # Binary STL: 80-byte header, then uint32 triangle count.
    if len(data) >= 84:
        return struct.unpack("<I", data[80:84])[0]
    return 0


def _check_board(board_id: str, mcu: str, openscad: str) -> tuple[bool, str]:
    try:
        scad = generate_scad(_minimal_design(board_id, mcu), default_library())
    except EnclosureUnavailable as e:
        return False, f"generator refused: {e}"
    with tempfile.TemporaryDirectory() as td:
        scad_file = Path(td) / f"{board_id}.scad"
        stl_file = Path(td) / f"{board_id}.stl"
        scad_file.write_text(scad)
        # Output format is inferred from the .stl extension -- portable
        # across OpenSCAD versions (the --export-format flag is newer).
        proc = subprocess.run(
            [openscad, "-o", str(stl_file), str(scad_file)],
            capture_output=True, text=True, timeout=300,
        )
        stderr = proc.stderr or ""
        errs = [ln for ln in stderr.splitlines() if re.search(r"\bERROR\b", ln)]
        if proc.returncode != 0 or errs:
            detail = "\n    ".join(errs[-4:] or [(stderr or proc.stdout).strip()[-300:]])
            return False, f"openscad failed (exit {proc.returncode}):\n    {detail}"
        # CGAL reports "Simple: yes/no" for the top-level solid; "no" means
        # self-intersecting / non-manifold geometry (won't slice cleanly).
        if re.search(r"Simple:\s+no", stderr):
            return False, "non-manifold solid (CGAL reports Simple: no)"
        if not stl_file.exists() or stl_file.stat().st_size == 0:
            return False, "no STL produced"
        tris = _stl_triangle_count(stl_file)
        if tris <= 0:
            return False, "empty solid (0 triangles)"
        return True, f"solid OK ({tris} triangles)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("boards", nargs="*", help="board ids (default: all with enclosure metadata)")
    parser.add_argument("--openscad", default=None, help="path to the openscad binary")
    args = parser.parse_args(argv)

    openscad = args.openscad or shutil.which("openscad")
    if not openscad:
        print("error: openscad not found. Install it (apt-get install openscad) "
              "or pass --openscad.", file=sys.stderr)
        return 2

    library = default_library()
    boards = library.list_boards()
    by_id = {b.id: b for b in boards}
    if args.boards:
        targets = [(b, by_id[b].mcu) for b in args.boards if b in by_id]
    else:
        targets = [(b.id, b.mcu) for b in boards if b.enclosure is not None]

    if not targets:
        print("error: no boards with enclosure metadata to check.", file=sys.stderr)
        return 2

    failures: list[tuple[str, str]] = []
    for board_id, mcu in targets:
        ok, detail = _check_board(board_id, mcu, openscad)
        if ok:
            print(f"  PASS  {board_id}  {detail}", file=sys.stderr)
        else:
            failures.append((board_id, detail))
            print(f"  FAIL  {board_id}  {detail}", file=sys.stderr)

    print(file=sys.stderr)
    if failures:
        print(f"{len(failures)} of {len(targets)} enclosures failed to render:", file=sys.stderr)
        for board_id, detail in failures:
            print(f"\n--- {board_id} ---\n{detail}", file=sys.stderr)
        return 1
    print(f"all {len(targets)} board enclosures render to a manifold solid.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
