"""Autoroute representative example boards and hold them to the routed bar.

Where check_pcb_drc.py proves KiCad accepts every placed-but-unrouted board
(waiving unconnected airwires), this gate runs the full Freerouting roundtrip
on a representative spread of examples and asserts the *routed* standard:
zero unconnected items, copper present, and no error-severity violations
beyond the footprint-inherent set the DRC tier already waives.

A representative subset, not every example: routing cost scales with board
density and the point is proving the pipeline, not re-routing the catalog
weekly.

Needs kicad-cli, a pcbnew-capable python (WIRESTUDIO_PCBNEW_PYTHON), java,
and WIRESTUDIO_FREEROUTING_JAR. Skips with exit 0 when the route toolchain
is absent so it's a no-op elsewhere.

Exit 0 = every representative board routes and passes routed DRC, 1 = at
least one failed, 2 = KiCad libraries not found.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from wirestudio.kicad.fab import is_routed
from wirestudio.kicad.pcb import generate_kicad_pcb, pcb_status
from wirestudio.kicad.route import RouteError, route_board, route_status
from wirestudio.library import default_library
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"

# Small, PWM-dense, I2C multi-sensor, many-connection: a spread of routing
# difficulty, not an exhaustive sweep.
REPRESENTATIVE = ["garage-motion", "solder-fan", "weather-station", "securitypanel"]

# The footprint-inherent waivers from check_pcb_drc.py — but NOT
# unconnected_items: a routed board with airwires is a routing failure.
_IGNORED_VIOLATIONS = {
    "drill_out_of_range",
    "solder_mask_bridge",
    "copper_edge_clearance",
    "courtyards_overlap",
    "silk_over_copper",
    "silk_overlap",
    "silk_edge_clearance",
}


def _routed_problems(report: Path) -> list[str]:
    data = json.loads(report.read_text())
    out = [
        f"{v.get('type')}: {v.get('description')}"
        for v in data.get("violations", [])
        if v.get("severity") == "error" and v.get("type") not in _IGNORED_VIOLATIONS
    ]
    unconnected = data.get("unconnected_items", [])
    if unconnected:
        out.append(f"{len(unconnected)} unconnected item(s) after routing")
    return out


def main() -> int:
    status = route_status()
    if not status["available"]:
        print(f"route toolchain unavailable; skipping (no-op): {status['reason']}",
              file=sys.stderr)
        return 0
    if shutil.which("kicad-cli") is None:
        print("kicad-cli not on PATH; skipping (no-op).", file=sys.stderr)
        return 0
    if not pcb_status()["available"]:
        print(f"error: {pcb_status()['reason']}", file=sys.stderr)
        return 2

    lib = default_library()
    failures: dict[str, list[str]] = {}
    with tempfile.TemporaryDirectory(prefix="wirestudio-route-") as td:
        tmp = Path(td)
        for name in REPRESENTATIVE:
            design = Design.model_validate(
                json.loads((EXAMPLES_DIR / f"{name}.json").read_text())
            )
            try:
                unrouted = generate_kicad_pcb(design, lib)
            except Exception as exc:  # noqa: BLE001
                failures[name] = [f"emit raised {type(exc).__name__}: {exc}"]
                continue
            try:
                routed = route_board(unrouted, use_cache=False)
            except RouteError as exc:
                failures[name] = [f"routing failed: {str(exc)[-800:]}"]
                continue
            if not is_routed(routed):
                failures[name] = ["routed board carries no copper"]
                continue
            board = tmp / f"{name}.kicad_pcb"
            board.write_text(routed)
            report = tmp / f"{name}.drc.json"
            proc = subprocess.run(
                ["kicad-cli", "pcb", "drc", "--format", "json",
                 "--output", str(report), str(board)],
                capture_output=True, text=True, timeout=180,
            )
            if not report.is_file():
                failures[name] = [f"kicad-cli produced no report (rc={proc.returncode}): "
                                  f"{(proc.stderr or proc.stdout or '')[-500:]}"]
                continue
            problems = _routed_problems(report)
            if problems:
                failures[name] = problems
            else:
                print(f"{name}: routed clean", file=sys.stderr)

    if failures:
        print(f"{len(failures)} board(s) failed the routed gate:", file=sys.stderr)
        for name, problems in failures.items():
            for p in problems:
                print(f"  {name}: {p}", file=sys.stderr)
        return 1
    print(f"all {len(REPRESENTATIVE)} representative boards route and pass routed DRC.",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
