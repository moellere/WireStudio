"""Verify every bundled example emits a structurally sound .kicad_pcb.

The fourth EDA gate, alongside check_schematics.py (symbols/netlist),
check_footprints.py (footprint existence), and check_examples.py (ESPHome
YAML). It generates each examples/*.json board against the pinned KiCad
footprint + symbol libraries and asserts structure that KiCad would reject if
wrong: the file parens-balance, at least one footprint embeds, and every net a
pad references is declared at board level.

This is the fast, KiCad-binary-free bar (the companion DRC tier in
pcb-layout.yml installs KiCad and runs `kicad-cli pcb drc` for the real
open-and-DRC check). It needs checkouts of kicad-footprints + kicad-symbols;
point KICAD8_FOOTPRINT_DIR + KICAD8_SYMBOL_DIR at them (CI clones both at a
pinned tag).

Run locally:
    git clone --depth 1 --branch 8.0.0 https://gitlab.com/kicad/libraries/kicad-footprints.git
    git clone --depth 1 --branch 8.0.0 https://gitlab.com/kicad/libraries/kicad-symbols.git
    export KICAD8_FOOTPRINT_DIR=$PWD/kicad-footprints
    export KICAD8_SYMBOL_DIR=$PWD/kicad-symbols
    python scripts/check_pcb.py

Exit 0 = every example emits a sound board, 1 = at least one failed, 2 =
libraries not found.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from wirestudio.kicad.pcb import generate_kicad_pcb, pcb_status
from wirestudio.library import default_library
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"


def _check(pcb: str) -> list[str]:
    """Return a list of structural problems with an emitted board (empty = ok)."""
    problems: list[str] = []
    if not pcb.startswith("(kicad_pcb"):
        problems.append("does not start with (kicad_pcb")
    if pcb.count("(") != pcb.count(")"):
        problems.append(f"unbalanced parens ({pcb.count('(')} vs {pcb.count(')')})")
    if not re.search(r'\(footprint "', pcb):
        problems.append("no footprints embedded")
    declared = {int(i) for i in re.findall(r'^\t\(net (\d+) "', pcb, re.M)}
    referenced = {int(i) for i in re.findall(r'^\t\t\t?\(net (\d+) "', pcb, re.M)}
    if not referenced <= declared:
        problems.append(f"pads reference undeclared nets: {sorted(referenced - declared)}")
    return problems


def main() -> int:
    status = pcb_status()
    if not status["available"]:
        print(f"error: {status['reason']}", file=sys.stderr)
        return 2

    lib = default_library()
    failures: dict[str, list[str]] = {}
    ok = 0
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        design = Design.model_validate(json.loads(path.read_text()))
        try:
            pcb = generate_kicad_pcb(design, lib)
        except Exception as exc:  # noqa: BLE001 -- surface any emit failure per example
            failures[path.stem] = [f"emit raised {type(exc).__name__}: {exc}"]
            continue
        problems = _check(pcb)
        if problems:
            failures[path.stem] = problems
        else:
            ok += 1

    if failures:
        print(f"{len(failures)} example(s) produced an unsound .kicad_pcb:", file=sys.stderr)
        for name, problems in failures.items():
            for p in problems:
                print(f"  {name}: {p}", file=sys.stderr)
        return 1

    print(f"all {ok} examples emit a structurally sound .kicad_pcb.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
