"""Verify every bundled example produces a real KiCad netlist via SKiDL.

The companion to `scripts/check_examples.py`. Where that gate proves the
ESPHome YAML round-trips through `esphome config`, this one proves the
generated schematic round-trips through real EDA tooling: for every
`examples/*.json` it renders the SKiDL script (`wirestudio.kicad.generate_skidl`),
then executes it against the actual KiCad symbol libraries and emits a
netlist. That exercises three things text-only tests can't:

  - every component / board `kicad:` block references a symbol that
    actually exists in the KiCad symbol libraries,
  - every connected pin role maps (via pin_map) to a real pin on that
    symbol -- SKiDL raises on an unknown pin,
  - the design assembles into a netlist without SKiDL erroring.

This is the "Verified" bar for the schematic feature: not "the emitted
Python is syntactically valid" but "it builds a netlist against KiCad's
own symbol set."

Requires SKiDL plus the KiCad symbol libraries. Point the gate at the
libraries with KICAD8_SYMBOL_DIR (or pass --symbol-dir). In CI the
workflow clones kicad-symbols at a pinned tag and sets that env var.

Run locally:
    pip install --no-deps skidl graphviz simp_sexp
    export KICAD8_SYMBOL_DIR=/path/to/kicad-symbols
    python scripts/check_schematics.py                 # all examples
    python scripts/check_schematics.py garage-motion    # just one

Exit code 0 = every example netlisted, 1 = at least one failed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from wirestudio.kicad.generator import generate_skidl
from wirestudio.library import default_library
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"

# Runner executed in a fresh subprocess per example. Execs the generated
# SKiDL source to pull in build(), pins the KiCad tool, builds the
# circuit, and writes a netlist. The generated file's __main__ block is
# inert here (we set a non-main module name), so generate_schematic() --
# SKiDL's flaky experimental step -- never runs; we validate at the
# netlist level only.
_RUNNER = """\
import os
import sys
import skidl
from skidl import generate_netlist

skidl.set_default_tool(skidl.KICAD8)
# Pin the symbol search path to the real kicad-symbols dir only. SKiDL
# defaults to including '.', which lets a stray <Lib>.kicad_sym in the
# tree (e.g. tests/fixtures/Sensor.kicad_sym) shadow the real library
# and cache a wrong, pin-incomplete symbol set.
_sym = next((os.environ[v] for v in (
    "KICAD8_SYMBOL_DIR", "KICAD9_SYMBOL_DIR", "KICAD7_SYMBOL_DIR",
    "KICAD6_SYMBOL_DIR", "KICAD_SYMBOL_DIR") if os.environ.get(v)), None)
if _sym:
    skidl.lib_search_paths[skidl.KICAD8] = [_sym]
src_path, net_path = sys.argv[1], sys.argv[2]
with open(src_path) as fh:
    src = fh.read()
ns = {"__name__": "_wirestudio_schematic"}
exec(compile(src, src_path, "exec"), ns)
ns["build"]()
generate_netlist(file_=net_path)
"""


def _symbol_dir_present() -> str | None:
    for var in ("KICAD8_SYMBOL_DIR", "KICAD9_SYMBOL_DIR", "KICAD7_SYMBOL_DIR",
                "KICAD6_SYMBOL_DIR", "KICAD_SYMBOL_DIR"):
        val = os.environ.get(var)
        if val and Path(val).is_dir():
            return val
    return None


def _check_one(stem: str, design_path: Path, runner: Path) -> tuple[bool, str]:
    design = Design.model_validate(json.loads(design_path.read_text()))
    src = generate_skidl(design, default_library())
    with tempfile.TemporaryDirectory() as td:
        src_file = Path(td) / f"{stem}.skidl.py"
        net_file = Path(td) / f"{stem}.net"
        src_file.write_text(src)
        proc = subprocess.run(
            [sys.executable, str(runner), str(src_file), str(net_file)],
            capture_output=True, text=True, timeout=120,
            # Run in the temp dir so SKiDL's side-effect files (_sklib.py
            # cache, .erc reports) land there and vanish with it instead
            # of littering the repo root / cwd.
            cwd=td,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()
            # Surface the SKiDL ERROR line(s), not the import-warning noise.
            errs = [ln for ln in tail if "ERROR" in ln or "Error" in ln]
            detail = "\n    ".join(errs[-4:] or tail[-4:])
            return False, f"SKiDL run failed:\n    {detail}"
        if not net_file.exists() or net_file.stat().st_size == 0:
            return False, "no netlist produced"
        comp_count = len(re.findall(r"\(comp\b", net_file.read_text()))
        return True, f"netlist OK ({comp_count} parts)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stems", nargs="*", help="example stems (default: all)")
    parser.add_argument(
        "--symbol-dir", type=Path, default=None,
        help="KiCad symbol library dir (else read KICAD*_SYMBOL_DIR env)",
    )
    args = parser.parse_args(argv)

    if args.symbol_dir:
        os.environ["KICAD8_SYMBOL_DIR"] = str(args.symbol_dir)
    sym_dir = _symbol_dir_present()
    if not sym_dir:
        print(
            "error: no KiCad symbol library found. Set KICAD8_SYMBOL_DIR "
            "(or pass --symbol-dir) to a checkout of kicad-symbols.",
            file=sys.stderr,
        )
        return 2
    # Probe without importing -- importing skidl in this parent process
    # registers an atexit ERC writer that drops a stray .erc in cwd. The
    # per-example subprocess does the actual skidl work.
    if importlib.util.find_spec("skidl") is None:
        print(
            "error: skidl not installed. `pip install --no-deps skidl "
            "graphviz simp_sexp`.",
            file=sys.stderr,
        )
        return 2

    if args.stems:
        paths = [EXAMPLES_DIR / f"{s}.json" for s in args.stems]
    else:
        paths = sorted(EXAMPLES_DIR.glob("*.json"))

    with tempfile.TemporaryDirectory() as td:
        runner = Path(td) / "_runner.py"
        runner.write_text(_RUNNER)
        failures: list[tuple[str, str]] = []
        for path in paths:
            stem = path.stem
            if not path.exists():
                failures.append((stem, "no such example"))
                print(f"  MISS  {stem}", file=sys.stderr)
                continue
            ok, detail = _check_one(stem, path, runner)
            if ok:
                print(f"  PASS  {stem}  {detail}", file=sys.stderr)
            else:
                failures.append((stem, detail))
                print(f"  FAIL  {stem}  {detail}", file=sys.stderr)

    print(file=sys.stderr)
    if failures:
        print(f"{len(failures)} of {len(paths)} examples failed to netlist:", file=sys.stderr)
        for stem, detail in failures:
            print(f"\n--- {stem} ---\n{detail}", file=sys.stderr)
        return 1
    print(f"all {len(paths)} examples netlist against KiCad symbols (tool KICAD8).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
