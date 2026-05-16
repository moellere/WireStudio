"""Walk a design's component BOM and check each part against JLCPCB stock.

Component instances are grouped by `library_id` (a design with two of the
same sensor produces one line with quantity 2). The search keyword is the
library id -- for most real parts (`bme280`, `hc-sr501`, `ssd1306`) that
*is* the part name. Virtual ESPHome platforms (`gpio_input`, `adc`, ...)
have no orderable part and land as `not_found`, which is honest.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from wirestudio.jlcpcb.client import JlcpcbClient, JlcpcbPart, JlcpcbUnavailable
from wirestudio.library import Library
from wirestudio.model import Design


@dataclass
class BomLine:
    library_id: str
    name: str
    quantity: int
    query: str
    status: str  # ok | out_of_stock | not_found
    note: str
    match: JlcpcbPart | None = None


@dataclass
class BomReport:
    design_id: str
    available: bool
    api_url: str
    lines: list[BomLine] = field(default_factory=list)
    reason: str | None = None

    @property
    def summary(self) -> dict[str, int]:
        out = {"ok": 0, "out_of_stock": 0, "not_found": 0}
        for ln in self.lines:
            out[ln.status] = out.get(ln.status, 0) + 1
        return out


def _classify(library_id: str, name: str, query: str, quantity: int,
              parts: list[JlcpcbPart]) -> BomLine:
    if not parts:
        return BomLine(library_id, name, quantity, query, "not_found",
                       "no JLCPCB match — source manually")
    best = parts[0]
    if best.stock <= 0:
        return BomLine(library_id, name, quantity, query, "out_of_stock",
                       f"{best.lcsc} matched but 0 in stock", match=best)
    price = f"${best.price:.2f}" if best.price is not None else "price n/a"
    tier = " [basic]" if best.basic else (" [preferred]" if best.preferred else "")
    note = f"{best.lcsc} — {best.stock} in stock @ {price}{tier}"
    return BomLine(library_id, name, quantity, query, "ok", note, match=best)


def check_bom(design: Design, library: Library,
              client: JlcpcbClient | None = None) -> BomReport:
    """Check every distinct component in `design` against JLCPCB stock.

    Never raises for an unreachable API: the report comes back with
    `available=False` and a `reason` so callers can degrade gracefully.
    """
    client = client or JlcpcbClient()
    report = BomReport(
        design_id=design.id or "design", available=True, api_url=client.base_url
    )

    counts: dict[str, int] = {}
    order: list[str] = []
    for comp in design.components:
        if comp.library_id not in counts:
            order.append(comp.library_id)
        counts[comp.library_id] = counts.get(comp.library_id, 0) + 1

    for library_id in order:
        try:
            name = library.component(library_id).name
        except FileNotFoundError:
            name = library_id
        try:
            parts = client.search(library_id)
        except JlcpcbUnavailable as exc:
            report.available = False
            report.reason = str(exc)
            return report
        report.lines.append(
            _classify(library_id, name, library_id, counts[library_id], parts)
        )
    return report


def report_to_dict(report: BomReport) -> dict:
    """JSON-serialisable view, shared by the CLI `--json` flag and the API."""
    return {
        "design_id": report.design_id,
        "available": report.available,
        "api_url": report.api_url,
        "reason": report.reason,
        "summary": report.summary,
        "lines": [
            {
                "library_id": ln.library_id,
                "name": ln.name,
                "quantity": ln.quantity,
                "query": ln.query,
                "status": ln.status,
                "note": ln.note,
                "match": None if ln.match is None else {
                    "lcsc": ln.match.lcsc,
                    "mfr": ln.match.mfr,
                    "package": ln.match.package,
                    "description": ln.match.description,
                    "stock": ln.match.stock,
                    "price": ln.match.price,
                    "basic": ln.match.basic,
                    "preferred": ln.match.preferred,
                },
            }
            for ln in report.lines
        ],
    }
