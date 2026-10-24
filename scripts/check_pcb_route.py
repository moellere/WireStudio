"""Autoroute representative example boards and hold them to the routed bar.

Where check_pcb_drc.py proves KiCad accepts every placed-but-unrouted board
(waiving unconnected airwires), this gate runs the full Freerouting roundtrip
on a representative spread of examples and asserts the *routed* standard:
zero unconnected items, copper present, and no error-severity violations
beyond the footprint-inherent set the DRC tier already waives. A board
with a GND net must come back with its GND pour filled, and one routed
board's B.Cu Gerber must carry the pour as a GND region.

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
import re
import shutil
import sys
import tempfile
from pathlib import Path

from wirestudio.kicad.drc import DrcError, run_drc
from wirestudio.kicad.fab import _gerbers_into, is_routed
from wirestudio.kicad.pcb import generate_kicad_pcb, pcb_status
from wirestudio.kicad.route import Keepout, RouteError, RouteParams, route_board, route_status
from wirestudio.library import default_library
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"

# Small, PWM-dense, I2C multi-sensor, many-connection: a spread of routing
# difficulty, not an exhaustive sweep.
REPRESENTATIVE = ["garage-motion", "solder-fan", "weather-station", "securitypanel"]

def _routed_problems(summary: dict) -> list[str]:
    """Anything the routed bar refuses: an airwire, or an error outside the
    waivers (wirestudio.kicad.drc.WAIVED, shared with the UI's report)."""
    out = [f"{g['type']}: {v['description']}"
           for g in summary["groups"]
           if g["severity"] == "error" and not g["waived"] and g["type"] != "unconnected_items"
           for v in g["violations"]]
    if summary["unconnected"]:
        out.append(f"{summary['unconnected']} unconnected item(s) after routing")
    return out


_SEGMENT = re.compile(r"\(segment\s*\(start ([\d.-]+) ([\d.-]+)\)\s*\(end ([\d.-]+) ([\d.-]+)\)")


def _vias(board: str) -> int:
    return len(re.findall(r"^\t\(via$", board, re.M))


def _crossings(board: str, k: Keepout) -> int:
    """Segments with a sampled point inside the keepout rectangle."""
    n = 0
    for m in _SEGMENT.finditer(board):
        x0, y0, x1, y1 = map(float, m.groups())
        if any(k.x <= x0 + (x1 - x0) * t / 20 <= k.x + k.w and k.y <= y0 + (y1 - y0) * t / 20 <= k.y + k.h
               for t in range(21)):
            n += 1
    return n


def _keepout_site(routed: str) -> Keepout | None:
    """A 3x3 mm keepout over the longest track it can cover without reaching
    within 1 mm of any track end, which is where the pads are."""
    segs = [tuple(map(float, m.groups())) for m in _SEGMENT.finditer(routed)]
    ends = [(x, y) for s in segs for x, y in (s[:2], s[2:])]
    for x0, y0, x1, y1 in sorted(segs, key=lambda s: -((s[2] - s[0]) ** 2 + (s[3] - s[1]) ** 2)):
        k = Keepout((x0 + x1) / 2 - 1.5, (y0 + y1) / 2 - 1.5, 3, 3)
        if not any(k.x - 1 <= x <= k.x + k.w + 1 and k.y - 1 <= y <= k.y + k.h + 1 for x, y in ends):
            return k
    return None


def _check_params(name: str, unrouted: str, routed: str) -> list[str]:
    """Route parameters do what they say on one board: a high via cost
    routes with fewer vias, and a keepout over a long default track (clear
    of the pads) moves the copper out of it, both still passing the routed
    bar."""
    out: list[str] = []
    cheap = route_board(unrouted, RouteParams(via_costs=2000), use_cache=False)
    if not _vias(cheap) < _vias(routed):
        out.append(f"via_costs=2000 left {_vias(cheap)} vias (default {_vias(routed)})")
    out += _routed_problems(run_drc(cheap))
    k = _keepout_site(routed)
    if k is None:
        return out + ["no track long enough to hold a keepout clear of every pad"]
    kept = route_board(unrouted, RouteParams(keepouts=(k,)), use_cache=False)
    if _crossings(kept, k):
        out.append(f"{_crossings(kept, k)} segment(s) still cross the keepout")
    out += _routed_problems(run_drc(kept))
    if not out:
        print(f"{name}: via cost {_vias(routed)} -> {_vias(cheap)} vias; keepout cleared, routed clean",
              file=sys.stderr)
    return out


def _pour_problems(routed: str) -> list[str]:
    if '(net_name "GND")' in routed and "(filled_polygon" not in routed:
        return ["the GND pour came back unfilled"]
    return []


def _gerber_pour_problems(routed: str) -> list[str]:
    with tempfile.TemporaryDirectory() as td:
        _gerbers_into(Path(td), routed)
        bottom = next(Path(td).glob("*B_Cu.gbl"), None)
        if bottom is None:
            return ["no B.Cu Gerber exported"]
        if not re.search(r"%TO\.N,GND\*%\s*G36\*", bottom.read_text()):
            return ["the B.Cu Gerber carries no GND region"]
    return []


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
    boards: dict[str, tuple[str, str]] = {}
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
        try:
            problems = _routed_problems(run_drc(routed)) + _pour_problems(routed)
        except DrcError as exc:
            failures[name] = [str(exc)]
            continue
        if problems:
            failures[name] = problems
        else:
            print(f"{name}: routed clean", file=sys.stderr)
            boards[name] = (unrouted, routed)

    if "garage-motion" in boards:
        problems = _gerber_pour_problems(boards["garage-motion"][1])
        if problems:
            failures["garage-motion (Gerbers)"] = problems
        else:
            print("garage-motion: B.Cu Gerber carries the GND pour", file=sys.stderr)
        problems = _check_params("garage-motion", *boards["garage-motion"])
        if problems:
            failures["garage-motion (route parameters)"] = problems

    # The same report on a board left unrouted must show its airwires:
    # a DRC path that reported nothing would pass every board above.
    unrouted = run_drc(generate_kicad_pcb(
        Design.model_validate(json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())), lib))
    if unrouted["unconnected"] == 0 or unrouted["ok"]:
        failures["garage-motion (unrouted)"] = ["DRC reported no unconnected items on an unrouted board"]
    else:
        print(f"garage-motion unrouted: {unrouted['unconnected']} unconnected, as expected",
              file=sys.stderr)

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
