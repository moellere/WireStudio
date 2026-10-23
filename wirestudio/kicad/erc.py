"""Electrical rules check on the written schematic via kicad-cli.

The render pipeline's sibling: design -> `.kicad_sch` -> `kicad-cli sch
erc`. Where the netlist gate proves every symbol and pin resolves and
`check_sch` proves the drawing carries the netlist, ERC is KiCad's own
judgement of the wiring: unconnected inputs, outputs tied together,
power pins nothing drives. Some of that is structural to how the sheet
is drawn (generic headers for parts KiCad has no symbol for), so
`scripts/check_erc.py` holds a baseline of the violation types the
writer cannot avoid and fails on anything else.

CLI: `python -m wirestudio.kicad.erc <design.json> [--json]`.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from wirestudio.kicad.render import (
    _TIMEOUT, RenderError, RenderUnavailable, render_status, write_schematic,
)
from wirestudio.library import Library, default_library
from wirestudio.migrate import load_design
from wirestudio.model import Design


def erc_status() -> dict:
    status = render_status()
    available = status["kicad_cli"] and status["symbols"]
    return {
        "available": available,
        "kicad_cli": status["kicad_cli"],
        "symbols": status["symbols"],
        "reason": None if available else status["reason"],
    }


def summarize(report: dict) -> dict:
    """Flatten kicad-cli's JSON ERC report into one list of violations
    plus per-type counts. Exclusions marked in the schematic are dropped."""
    violations: list[dict] = []
    for sheet in report.get("sheets", []):
        for v in sheet.get("violations", []):
            if v.get("excluded"):
                continue
            violations.append({
                "type": str(v.get("type", "")),
                "severity": str(v.get("severity", "")),
                "description": str(v.get("description", "")),
                "sheet": str(sheet.get("path", "/")),
                "items": [str(i.get("description", "")) for i in v.get("items", []) if isinstance(i, dict)],
            })
    counts = Counter(v["type"] for v in violations)
    return {
        "kicad_version": report.get("kicad_version"),
        "violations": violations,
        "counts": dict(sorted(counts.items())),
        "errors": sum(1 for v in violations if v["severity"] == "error"),
        "warnings": sum(1 for v in violations if v["severity"] == "warning"),
    }


def run_erc(design: Design, library: Library) -> dict:
    """ERC the design's schematic. Raises `RenderUnavailable` when a tool
    is missing and `RenderError` when a step fails."""
    status = erc_status()
    if not status["kicad_cli"]:
        raise RenderUnavailable("kicad-cli not found on PATH")
    if not status["symbols"]:
        raise RenderUnavailable(status["reason"])

    with tempfile.TemporaryDirectory(prefix="wirestudio-erc-") as td:
        tmp = Path(td)
        sch = write_schematic(design, library, tmp)
        report_path = tmp / "erc.json"
        cli_run = subprocess.run(
            [
                "kicad-cli", "sch", "erc", "--format", "json", "--severity-all",
                "--output", str(report_path), str(sch),
            ],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
        if cli_run.returncode != 0 or not report_path.exists():
            raise RenderError(
                "kicad-cli erc failed:\n" + ((cli_run.stdout or "") + (cli_run.stderr or ""))[-2000:]
            )
        try:
            report = json.loads(report_path.read_text())
        except ValueError as e:
            raise RenderError(f"kicad-cli erc wrote no JSON report: {e}") from e
    return summarize(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("design", help="path to a design.json")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)
    design = load_design(json.loads(Path(args.design).read_text()))
    try:
        result = run_erc(design, default_library())
    except (RenderUnavailable, RenderError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"kicad {result['kicad_version']}: {result['errors']} errors, {result['warnings']} warnings")
    for v in result["violations"]:
        print(f"  [{v['severity']}] {v['type']}: {v['description']}")
        for item in v["items"]:
            print(f"      {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
