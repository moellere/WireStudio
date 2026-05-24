"""Verify every library component + board references a real KiCad footprint.

The third EDA gate, alongside `check_schematics.py` (symbols/netlist) and
`check_examples.py` (ESPHome YAML). Where the schematic gate proves each
`kicad:` block's *symbol* exists in the KiCad symbol libraries, this one
proves its *footprint* exists in the KiCad footprint libraries -- the
prerequisite for any PCB layout. It checks two things:

  - coverage: every component and board with a `kicad:` block declares a
    `footprint`,
  - existence: each `LIB:NAME` footprint resolves to a real
    `LIB.pretty/NAME.kicad_mod` in the pinned KiCad footprint libraries.

This is the "Verified" bar for footprint assignment: not "a string is
present" but "it names a footprint KiCad actually ships."

Requires a checkout of kicad-footprints. Point the gate at it with
KICAD8_FOOTPRINT_DIR (or pass --footprint-dir). In CI the workflow clones
kicad-footprints at a pinned tag and sets that env var.

Run locally:
    git clone --depth 1 --branch 8.0.0 \\
        https://gitlab.com/kicad/libraries/kicad-footprints.git
    export KICAD8_FOOTPRINT_DIR=$PWD/kicad-footprints
    python scripts/check_footprints.py

Exit code 0 = every component + board has a real footprint, 1 = at least
one is missing or unresolved, 2 = footprint libraries not found.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from wirestudio.library import default_library

REPO_ROOT = Path(__file__).resolve().parent.parent
LIB_ROOT = REPO_ROOT / "wirestudio" / "library"

_FOOTPRINT_ENV_VARS = (
    "KICAD8_FOOTPRINT_DIR",
    "KICAD9_FOOTPRINT_DIR",
    "KICAD7_FOOTPRINT_DIR",
    "KICAD6_FOOTPRINT_DIR",
    "KICAD_FOOTPRINT_DIR",
)


def _footprint_dir() -> Path | None:
    for var in _FOOTPRINT_ENV_VARS:
        val = os.environ.get(var)
        if val and Path(val).is_dir():
            return Path(val)
    return None


def _resolves(footprint: str, fp_dir: Path) -> bool:
    """A footprint reference is `LIB:NAME` -> `LIB.pretty/NAME.kicad_mod`."""
    if ":" not in footprint:
        return False
    lib, name = footprint.split(":", 1)
    return (fp_dir / f"{lib}.pretty" / f"{name}.kicad_mod").is_file()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--footprint-dir", type=Path, default=None,
        help="KiCad footprint library dir (else read KICAD*_FOOTPRINT_DIR env)",
    )
    args = parser.parse_args(argv)

    if args.footprint_dir:
        os.environ["KICAD8_FOOTPRINT_DIR"] = str(args.footprint_dir)
    fp_dir = _footprint_dir()
    if not fp_dir:
        print(
            "error: no KiCad footprint library found. Set "
            "KICAD8_FOOTPRINT_DIR (or pass --footprint-dir) to a checkout "
            "of kicad-footprints.",
            file=sys.stderr,
        )
        return 2

    lib = default_library()
    entries: list[tuple[str, str, object]] = []
    for path in sorted((LIB_ROOT / "components").glob("*.yaml")):
        entries.append(("component", path.stem, lib.component(path.stem)))
    for path in sorted((LIB_ROOT / "boards").glob("*.yaml")):
        entries.append(("board", path.stem, lib.board(path.stem)))

    missing: list[str] = []   # no footprint declared
    unresolved: list[str] = []  # footprint named but not in the libraries
    ok = 0
    for kind, lib_id, entry in entries:
        kicad = getattr(entry, "kicad", None)
        if kicad is None:
            # No schematic mapping at all -> not placeable; surface it.
            missing.append(f"{kind} {lib_id}: no kicad block")
            continue
        if not kicad.footprint:
            missing.append(f"{kind} {lib_id}: no footprint")
            continue
        if not _resolves(kicad.footprint, fp_dir):
            unresolved.append(f"{kind} {lib_id}: {kicad.footprint}")
            continue
        ok += 1

    if missing or unresolved:
        if missing:
            print(f"{len(missing)} entr(ies) missing a footprint:", file=sys.stderr)
            for m in missing:
                print(f"  MISSING  {m}", file=sys.stderr)
        if unresolved:
            print(
                f"\n{len(unresolved)} footprint(s) not in kicad-footprints "
                f"({fp_dir.name}):",
                file=sys.stderr,
            )
            for u in unresolved:
                print(f"  UNRESOLVED  {u}", file=sys.stderr)
        return 1

    print(f"all {ok} library footprints resolve against {fp_dir.name}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
