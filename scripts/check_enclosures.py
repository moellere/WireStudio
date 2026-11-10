"""Verify every board's parametric enclosure renders to a valid solid.

The third correctness gate, alongside `check_examples.py` (ESPHome YAML)
and `check_schematics.py` (KiCad netlist). The OpenSCAD enclosure
generator (`wirestudio.enclosure.generate_scad`) builds the shell from
the board's `enclosure:` block, plus the panel parts (components and
modules with their own `enclosure:` block) a design places in it. This
renders a bare shell for every board that carries enclosure metadata,
then every bundled example that takes the panel layout, through real
OpenSCAD, and checks each result is a non-empty manifold solid.

OpenSCAD's Manifold backend errors on non-manifold geometry, so a clean
render to a triangle-bearing STL is the bar: it proves the generated
shell is a closed, printable solid, not just text that parses.

Requires the `openscad` CLI. In CI the workflow apt-installs it.

Run locally:
    sudo apt-get install -y openscad   # or your platform's package
    python scripts/check_enclosures.py              # all boards + panel examples
    python scripts/check_enclosures.py wemos-d1-mini
    python scripts/check_enclosures.py wall-panel   # an example by name

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
from wirestudio.enclosure.openscad import _panel_parts
from wirestudio.library import default_library
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"


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


def _panel_examples() -> dict[str, Design]:
    """Examples whose enclosure is more than the bare board shell."""
    library = default_library()
    out = {}
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        design = Design.model_validate_json(path.read_text())
        board = library.board(design.board.library_id)
        if board.enclosure is not None and (design.enclosure is not None or _panel_parts(design, library)):
            out[path.stem] = design
    return out


def _check_design(name: str, design: Design, openscad: str) -> tuple[bool, str]:
    try:
        scad = generate_scad(design, default_library())
    except EnclosureUnavailable as e:
        return False, f"generator refused: {e}"
    with tempfile.TemporaryDirectory() as td:
        scad_file = Path(td) / f"{name}.scad"
        stl_file = Path(td) / f"{name}.stl"
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
    parser.add_argument("targets", nargs="*",
                        help="board ids or example names (default: every board with enclosure "
                             "metadata and every panel example)")
    parser.add_argument("--openscad", default=None, help="path to the openscad binary")
    args = parser.parse_args(argv)

    openscad = args.openscad or shutil.which("openscad")
    if not openscad:
        print("error: openscad not found. Install it (apt-get install openscad) "
              "or pass --openscad.", file=sys.stderr)
        return 2

    library = default_library()
    boards = {b.id: b for b in library.list_boards()}
    examples = _panel_examples()
    targets: list[tuple[str, Design]] = []
    for name in args.targets or [b.id for b in boards.values() if b.enclosure is not None] + list(examples):
        if name in boards:
            targets.append((name, _minimal_design(name, boards[name].mcu)))
        elif name in examples:
            targets.append((name, examples[name]))

    if not targets:
        print("error: nothing with enclosure metadata to check.", file=sys.stderr)
        return 2

    failures: list[tuple[str, str]] = []
    for name, design in targets:
        ok, detail = _check_design(name, design, openscad)
        if ok:
            print(f"  PASS  {name}  {detail}", file=sys.stderr)
        else:
            failures.append((name, detail))
            print(f"  FAIL  {name}  {detail}", file=sys.stderr)

    print(file=sys.stderr)
    if failures:
        print(f"{len(failures)} of {len(targets)} enclosures failed to render:", file=sys.stderr)
        for name, detail in failures:
            print(f"\n--- {name} ---\n{detail}", file=sys.stderr)
        return 1
    print(f"all {len(targets)} enclosures render to a manifold solid.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
