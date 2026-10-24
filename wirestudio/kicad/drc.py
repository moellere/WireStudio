"""Design rules check on a board via kicad-cli.

ERC's sibling for the PCB: `.kicad_pcb` -> `kicad-cli pcb drc`. After a
route this is the routed verdict the UI and `route_pcb` report: how many
connections are still airwires, and every violation grouped by type.

Some violation types come from the footprints or KiCad's default rules
rather than from anything the studio places or routes (a module's 0.2 mm
vias under the default 0.3 mm minimum, mask slivers between fine-pitch
pads). Those are WAIVED: listed, counted, never failing. The CI tiers
(`scripts/check_pcb_drc.py`, `scripts/check_pcb_route.py`) hold boards to
the same list.

CLI: `python -m wirestudio.kicad.drc <board.kicad_pcb> [--json]`.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_TIMEOUT = 180

# Type -> why it does not reflect the studio's placement or routing.
WAIVED: dict[str, str] = {
    "drill_out_of_range": "module footprints carry vias smaller than KiCad's default minimum hole",
    "solder_mask_bridge": "fine-pitch footprints leave mask slivers under the default expansion",
    "copper_edge_clearance": "edge-mounted module footprints sit on the board outline",
    "courtyards_overlap": "module footprints overlap their own courtyards",
    "silk_over_copper": "cosmetic: footprint silkscreen over pads",
    "silk_overlap": "cosmetic: footprint silkscreen overlap",
    "silk_edge_clearance": "cosmetic: footprint silkscreen near the edge",
    "lib_footprint_issues": "the footprint differs from the installed library copy",
    "lib_footprint_mismatch": "the footprint differs from the installed library copy",
}

_SEVERITY_ORDER = {"error": 0, "warning": 1}


def drc_status() -> dict:
    available = shutil.which("kicad-cli") is not None
    return {"available": available, "reason": None if available else "kicad-cli not found on PATH"}


def _item(i: dict) -> dict:
    pos = i.get("pos") or {}
    return {"description": str(i.get("description", "")),
            "pos": {"x": pos.get("x"), "y": pos.get("y")} if pos else None}


def summarize(report: dict) -> dict:
    """kicad-cli's DRC JSON as groups by type: the unconnected count first,
    then errors, warnings, and the waived types last. `ok` means a routed
    board: no airwire and no error outside the waivers."""
    groups: dict[str, dict] = {}

    def add(v: dict) -> None:
        t = str(v.get("type", ""))
        g = groups.setdefault(t, {
            "type": t, "severity": str(v.get("severity", "")), "count": 0,
            "waived": t in WAIVED, "reason": WAIVED.get(t), "violations": [],
        })
        g["count"] += 1
        if _SEVERITY_ORDER.get(str(v.get("severity")), 9) < _SEVERITY_ORDER.get(g["severity"], 9):
            g["severity"] = str(v.get("severity"))
        g["violations"].append({
            "description": str(v.get("description", "")),
            "items": [_item(i) for i in v.get("items", []) if isinstance(i, dict)],
        })

    for v in report.get("violations", []):
        if not v.get("excluded"):
            add(v)
    for v in report.get("unconnected_items", []):
        add({**v, "type": "unconnected_items"})

    def order(g: dict):
        return (g["type"] != "unconnected_items", g["waived"], _SEVERITY_ORDER.get(g["severity"], 9), g["type"])

    ordered = sorted(groups.values(), key=order)
    unconnected = groups.get("unconnected_items", {}).get("count", 0)
    errors = sum(g["count"] for g in ordered
                 if g["severity"] == "error" and not g["waived"] and g["type"] != "unconnected_items")
    return {
        "kicad_version": report.get("kicad_version"),
        "ok": unconnected == 0 and errors == 0,
        "unconnected": unconnected,
        "errors": errors,
        "warnings": sum(g["count"] for g in ordered if g["severity"] == "warning" and not g["waived"]),
        "waived": sum(g["count"] for g in ordered if g["waived"]),
        "groups": ordered,
    }


class DrcError(RuntimeError):
    """kicad-cli ran and produced no report."""


def run_drc(board_text: str) -> dict:
    """DRC the board text. Raises DrcError when kicad-cli is missing or
    writes no report."""
    if not drc_status()["available"]:
        raise DrcError("kicad-cli not found on PATH")
    with tempfile.TemporaryDirectory(prefix="wirestudio-drc-") as td:
        board = Path(td) / "board.kicad_pcb"
        report = Path(td) / "drc.json"
        board.write_text(board_text)
        proc = subprocess.run(
            ["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all",
             "--output", str(report), str(board)],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
        if not report.is_file():
            raise DrcError(f"kicad-cli pcb drc wrote no report (rc={proc.returncode}): "
                           + ((proc.stdout or "") + (proc.stderr or ""))[-1500:])
        return summarize(json.loads(report.read_text()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("board", help="path to a .kicad_pcb")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)
    try:
        result = run_drc(Path(args.board).read_text())
    except DrcError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"kicad {result['kicad_version']}: {result['unconnected']} unconnected, "
          f"{result['errors']} errors, {result['warnings']} warnings, {result['waived']} waived")
    for g in result["groups"]:
        tag = "waived" if g["waived"] else g["severity"]
        print(f"  [{tag}] {g['type']} x{g['count']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
