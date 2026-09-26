#!/usr/bin/env python3
"""ERC the generated schematics of representative examples on real KiCad.

The render gate proves kicad-cli parses what SKiDL emits; this gate asks
kicad-cli what it thinks of the wiring. Every violation type it reports
must either be listed in `scripts/erc_baseline.yaml`, with the reason the
generator cannot avoid it, or it fails the run. The baseline is held to
the same rule as the coverage baseline: an entry that no example raises
any more must be removed, so the list stays a statement of fact.

Needs kicad-cli 8 on PATH, SKiDL, and KICAD8_SYMBOL_DIR pointing at a
kicad-symbols checkout (the render workflow sets all three).

    python scripts/check_erc.py                 # the representative set
    python scripts/check_erc.py bench-io        # one example, no stale check
    python scripts/check_erc.py --all           # every bundled example

Exit code 0 = clean against the baseline, 1 = unexpected violations or a
stale baseline entry, 2 = tools missing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from wirestudio.kicad.erc import erc_status, run_erc
from wirestudio.kicad.render import RenderError
from wirestudio.library import default_library
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"
BASELINE = REPO_ROOT / "scripts" / "erc_baseline.yaml"

# The render gate's two examples plus the subcircuit board, whose discrete
# parts carry real symbols and so give ERC something beyond headers.
DEFAULT_STEMS = ["garage-motion", "analog-node", "bench-io"]


def load_baseline(path: Path = BASELINE) -> dict[str, str]:
    data = yaml.safe_load(path.read_text()) or {}
    allowed = data.get("allowed") or {}
    return {str(k): str(v) for k, v in allowed.items()}


def judge(results: dict[str, dict], allowed: dict[str, str], *, check_stale: bool) -> tuple[list[str], list[str]]:
    """(failures, stale): violations outside the baseline per example, and
    baseline types no example raised when `check_stale`."""
    failures: list[str] = []
    seen: set[str] = set()
    for stem, result in sorted(results.items()):
        for v in result["violations"]:
            seen.add(v["type"])
            if v["type"] not in allowed:
                first = f" ({v['items'][0]})" if v["items"] else ""
                failures.append(f"{stem}: [{v['severity']}] {v['type']}: {v['description']}{first}")
    stale = sorted(t for t in allowed if t not in seen) if check_stale else []
    return failures, stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stems", nargs="*", help="example stems (default: the representative set)")
    parser.add_argument("--all", action="store_true", help="every bundled example")
    parser.add_argument("--report", type=Path, default=None, help="directory to write one JSON report per example")
    args = parser.parse_args(argv)

    status = erc_status()
    if not status["available"]:
        print(f"error: {status['reason']}", file=sys.stderr)
        return 2

    if args.all:
        paths = sorted(EXAMPLES_DIR.glob("*.json"))
    elif args.stems:
        paths = [EXAMPLES_DIR / f"{s}.json" for s in args.stems]
    else:
        paths = [EXAMPLES_DIR / f"{s}.json" for s in DEFAULT_STEMS]
    check_stale = not args.stems

    lib = default_library()
    allowed = load_baseline()
    results: dict[str, dict] = {}
    broken: list[str] = []
    for path in paths:
        stem = path.stem
        if not path.exists():
            broken.append(f"{stem}: no such example")
            continue
        design = Design.model_validate(json.loads(path.read_text()))
        try:
            result = run_erc(design, lib)
        except RenderError as e:
            broken.append(f"{stem}: {e}")
            print(f"  FAIL  {stem}  {str(e).splitlines()[0]}", file=sys.stderr)
            continue
        results[stem] = result
        if args.report:
            args.report.mkdir(parents=True, exist_ok=True)
            (args.report / f"{stem}.json").write_text(json.dumps(result, indent=2))
        counts = ", ".join(f"{t}={n}" for t, n in result["counts"].items()) or "clean"
        print(f"  ERC   {stem}  {result['errors']} errors, {result['warnings']} warnings  ({counts})", file=sys.stderr)

    failures, stale = judge(results, allowed, check_stale=check_stale)

    print(file=sys.stderr)
    if broken:
        print("Could not ERC:", file=sys.stderr)
        for line in broken:
            print(f"  {line}", file=sys.stderr)
    if failures:
        print("Violations outside scripts/erc_baseline.yaml:", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        print(
            "\nFix the generator or the library entry, or add the type to the\n"
            "baseline with the reason it cannot be avoided.",
            file=sys.stderr,
        )
    if stale:
        print("Baseline entries no example raises any more (remove them):", file=sys.stderr)
        for t in stale:
            print(f"  {t}", file=sys.stderr)
    if broken or failures or stale:
        return 1
    print(f"OK: {len(results)} examples ERC-clean against the baseline.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
