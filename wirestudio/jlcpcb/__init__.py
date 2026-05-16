"""JLCPCB BOM feasibility check.

`python -m wirestudio.jlcpcb check <design.json>` walks a design's
component BOM, queries a JLCPCB parts search API, and reports stock +
price per part -- a pre-PCB-order feasibility gate. `status` probes the
API. The same `check_bom` powers `POST /design/jlcpcb/check`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wirestudio.jlcpcb.check import BomLine, BomReport, check_bom, report_to_dict
from wirestudio.jlcpcb.client import (
    JlcpcbClient,
    JlcpcbPart,
    JlcpcbUnavailable,
    jlcpcb_status,
)
from wirestudio.library import default_library
from wirestudio.model import Design

__all__ = [
    "BomLine",
    "BomReport",
    "JlcpcbClient",
    "JlcpcbPart",
    "JlcpcbUnavailable",
    "check_bom",
    "jlcpcb_status",
    "report_to_dict",
    "main",
]

_STATUS_LABEL = {"ok": "OK", "out_of_stock": "OUT OF STOCK", "not_found": "NOT FOUND"}


def _print_report(report: BomReport) -> None:
    host = report.api_url.split("//")[-1]
    print(f"JLCPCB BOM check — {report.design_id}   ({host})")
    if not report.available:
        print(f"  unavailable: {report.reason}")
        return
    if not report.lines:
        print("  (no components in the design)")
        return
    width = max(len(ln.library_id) for ln in report.lines)
    for ln in report.lines:
        qty = f"x{ln.quantity}"
        print(f"  {ln.library_id:<{width}}  {qty:<4} {ln.note}"
              f"   {_STATUS_LABEL[ln.status]}")
    s = report.summary
    print(f"  {s['ok']} ok · {s['out_of_stock']} out of stock · "
          f"{s['not_found']} not found")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wirestudio.jlcpcb",
        description="Check a design's BOM against JLCPCB part stock.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_check = sub.add_parser("check", help="check a design.json BOM against JLCPCB")
    p_check.add_argument("design", help="path to a design.json")
    p_check.add_argument("--json", action="store_true", help="emit the report as JSON")
    sub.add_parser("status", help="probe the JLCPCB search API")

    args = parser.parse_args(argv)

    if args.cmd == "status":
        status = jlcpcb_status()
        print(json.dumps(status, indent=2))
        return 0 if status["available"] else 2

    design = Design.model_validate(json.loads(Path(args.design).read_text()))
    report = check_bom(design, default_library())
    if args.json:
        print(json.dumps(report_to_dict(report), indent=2))
    else:
        _print_report(report)
    if not report.available:
        print(f"error: {report.reason}", file=sys.stderr)
        return 2
    return 0
