"""Does the written schematic connect what the netlist says.

For every bundled example (or the stems given) the sheet is written with
`wirestudio.kicad.schematic`, KiCad reads its netlist back from the
geometry (`kicad-cli sch export netlist`), and the pin groups are compared
with the ones the writer meant to draw: a wire that misses a pin, a label
on the wrong net or a missing junction shows up here as a split or merged
group. Named nets (rails, GPIO_*, BUS_*) must also keep their names.
Pins a subcircuit layout left for the fallback stub are reported, since
that is the layout being incomplete, not wrong.

Needs kicad-cli and the KiCad symbol library (KICAD8_SYMBOL_DIR).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from wirestudio.kicad.schematic import (  # noqa: E402
    SchematicUnavailable, build_sheet, expected_connectivity, render_sheet, sch_status,
)
from wirestudio.kicad.symbol_parser import parse_sexpr  # noqa: E402
from wirestudio.library import default_library  # noqa: E402
from wirestudio.model import Design  # noqa: E402

EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"


def kicad_groups(netlist_text: str) -> tuple[set[frozenset[tuple[str, str]]], dict[frozenset, str]]:
    """Pin groups KiCad found, power symbols left out, with each group's name."""
    tree = parse_sexpr(netlist_text)
    groups: set[frozenset] = set()
    names: dict[frozenset, str] = {}
    nets = next((c for c in tree[1:] if isinstance(c, list) and c and c[0] == "nets"), [])
    for net in nets[1:]:
        if not isinstance(net, list) or net[0] != "net":
            continue
        name = next((str(c[1]) for c in net if isinstance(c, list) and c[0] == "name"), "")
        pins = set()
        for node in net:
            if isinstance(node, list) and node[0] == "node":
                ref = next(str(c[1]) for c in node if isinstance(c, list) and c[0] == "ref")
                pin = next(str(c[1]) for c in node if isinstance(c, list) and c[0] == "pin")
                if not ref.startswith("#"):
                    pins.add((ref, pin))
        if len(pins) > 1:
            g = frozenset(pins)
            groups.add(g)
            names[g] = name
    return groups, names


def check(path: Path, lib, out_dir: Path | None) -> list[str]:
    design = Design.model_validate(json.loads(path.read_text()))
    sheet = build_sheet(design, lib)
    text = render_sheet(sheet)
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="wirestudio-sch-") as td:
        sch = Path(td) / f"{design.id}.kicad_sch"
        sch.write_text(text)
        net = Path(td) / "out.net"
        run = subprocess.run(
            ["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr",
             "--output", str(net), str(sch)],
            capture_output=True, text=True, timeout=180,
        )
        if run.returncode != 0 or not net.exists():
            return [f"kicad-cli netlist failed: {(run.stdout + run.stderr)[-500:]}"]
        got, names = kicad_groups(net.read_text())
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / sch.name).write_text(text)
    want = expected_connectivity(sheet)
    want_names = {}
    for (ref, number), name in sheet.pin_nets.items():
        want_names.setdefault(name, set()).add((ref, number))
    wanted_pins = set().union(*want) if want else set()
    for g in sorted(want - got, key=sorted):
        problems.append(f"group not connected as drawn: {sorted(g)}")
    for g in sorted(got - want, key=sorted):
        # KiCad joins a symbol's same-named power pins on its own (a
        # module's GNDs); unconnected, that is a group the netlist never
        # had and no wire of ours drew.
        if len({ref for ref, _ in g}) == 1 and not (g & wanted_pins):
            continue
        problems.append(f"KiCad connects a group the netlist does not: {sorted(g)} ({names.get(g)})")
    for name, pins in want_names.items():
        if len(pins) > 1 and name[:1] in ("+", "G", "B") and frozenset(pins) in names:
            if names[frozenset(pins)] != name:
                problems.append(f"net {name} came back named {names[frozenset(pins)]!r}")
    for note in sheet.notes:
        problems.append(f"note: {note}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stems", nargs="*", help="example stems (default: all)")
    parser.add_argument("--out", type=Path, default=None, help="directory to keep the written sheets")
    args = parser.parse_args(argv)
    if shutil.which("kicad-cli") is None:
        print("error: kicad-cli not on PATH", file=sys.stderr)
        return 2
    status = sch_status()
    if not status["available"]:
        print(f"error: {status['reason']}", file=sys.stderr)
        return 2
    paths = [EXAMPLES_DIR / f"{s}.json" for s in args.stems] or sorted(EXAMPLES_DIR.glob("*.json"))
    lib = default_library()
    failed = 0
    for path in paths:
        try:
            problems = check(path, lib, args.out)
        except (SchematicUnavailable, FileNotFoundError, ValueError) as e:
            problems = [f"could not write: {e}"]
        hard = [p for p in problems if not p.startswith("note:")]
        notes = [p for p in problems if p.startswith("note:")]
        verdict = "FAIL" if hard else "PASS"
        print(f"  {verdict}  {path.stem}  ({len(notes)} note{'s' if len(notes) != 1 else ''})", file=sys.stderr)
        for p in problems:
            print(f"        {p}", file=sys.stderr)
        failed += bool(hard)
    print(file=sys.stderr)
    if failed:
        print(f"{failed} of {len(paths)} sheets do not connect what their netlist says.", file=sys.stderr)
        return 1
    print(f"all {len(paths)} sheets connect what their netlist says.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
