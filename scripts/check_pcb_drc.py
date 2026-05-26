"""Open every example's emitted .kicad_pcb in real KiCad and run DRC.

The "Verified" tier for the board emitter, above the structural check_pcb.py:
where that asserts the text is well-formed, this proves KiCad itself accepts
the file -- it parses, the embedded footprints load, and the netlist builds.

The boards are placed but NOT routed, so every net is an unconnected airwire;
those `unconnected_items` are expected and ignored. Any other error-severity
DRC violation (a malformed footprint, an unparsable board, a bad net ref) fails
the gate. We also assert kicad-cli can open the board at all.

Needs `kicad-cli` on PATH (CI runs this in the kicad/kicad image, which also
ships the standard footprint + symbol libraries). Skips with exit 0 when
kicad-cli is absent so it's a no-op in environments without KiCad.

Run in the kicad image:
    export KICAD8_FOOTPRINT_DIR=/usr/share/kicad/footprints
    export KICAD8_SYMBOL_DIR=/usr/share/kicad/symbols
    python scripts/check_pcb_drc.py

Exit 0 = every board opens and is DRC-clean (modulo unconnected), 1 = at least
one failed, 2 = libraries not found.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from wirestudio.kicad.pcb import generate_kicad_pcb, pcb_status
from wirestudio.library import default_library
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"

# Violation types that are expected on a placed-but-unrouted board and are not
# the board emitter's concern at this step.
_IGNORED_VIOLATIONS = {"unconnected_items"}


def _run_drc(board: Path, report: Path) -> tuple[int, str]:
    proc = subprocess.run(
        ["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(board)],
        capture_output=True, text=True, timeout=180,
    )
    return proc.returncode, (proc.stderr or proc.stdout or "")


def _real_violations(report: Path) -> list[str]:
    """Error-severity DRC violations that aren't the expected unconnected
    airwires. Returns a list of human-readable descriptions."""
    data = json.loads(report.read_text())
    out: list[str] = []
    for v in data.get("violations", []):
        if v.get("type") in _IGNORED_VIOLATIONS:
            continue
        if v.get("severity") == "error":
            out.append(f"{v.get('type')}: {v.get('description')}")
    return out


def main() -> int:
    if shutil.which("kicad-cli") is None:
        print("kicad-cli not on PATH; skipping the DRC tier (no-op).", file=sys.stderr)
        return 0

    status = pcb_status()
    if not status["available"]:
        print(f"error: {status['reason']}", file=sys.stderr)
        return 2

    lib = default_library()
    failures: dict[str, list[str]] = {}
    ok = 0
    with tempfile.TemporaryDirectory(prefix="wirestudio-drc-") as td:
        tmp = Path(td)
        for path in sorted(EXAMPLES_DIR.glob("*.json")):
            design = Design.model_validate(json.loads(path.read_text()))
            board = tmp / f"{path.stem}.kicad_pcb"
            try:
                board.write_text(generate_kicad_pcb(design, lib))
            except Exception as exc:  # noqa: BLE001
                failures[path.stem] = [f"emit raised {type(exc).__name__}: {exc}"]
                continue
            report = tmp / f"{path.stem}.drc.json"
            rc, err = _run_drc(board, report)
            if not report.is_file():
                failures[path.stem] = [f"kicad-cli produced no report (rc={rc}): {err[-500:]}"]
                continue
            problems = _real_violations(report)
            if problems:
                failures[path.stem] = problems
            else:
                ok += 1

    if failures:
        print(f"{len(failures)} example(s) failed KiCad DRC:", file=sys.stderr)
        for name, problems in failures.items():
            for p in problems:
                print(f"  {name}: {p}", file=sys.stderr)
        return 1

    print(f"all {ok} example boards open in KiCad and pass DRC (modulo unrouted).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
