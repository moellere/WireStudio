"""What to order: the inventory check's shortfalls, priced on JLCPCB.

The check says what is short; this joins each shortfall with the same
parts search the BOM stock check uses. A library component searches by
its id, a semiconductor by MPN, a passive by value and family. Common
passives the check marks `assumed` are not bought.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Union

from wirestudio.inventory.check import check_inventory
from wirestudio.inventory.store import InventoryEntry
from wirestudio.jlcpcb.check import classify
from wirestudio.jlcpcb.client import JlcpcbClient, JlcpcbUnavailable
from wirestudio.library import Library
from wirestudio.model import Design


@dataclass
class BuyLine:
    label: str
    kind: str  # component | module | part
    family: str
    shortfall: int
    refs: list[str]
    query: str
    status: str  # ok | out_of_stock | not_found
    note: str
    lcsc: str = ""
    mfr: str = ""
    package: str = ""
    stock: int = 0
    price: float | None = None


@dataclass
class BuyList:
    design_id: str
    available: bool
    api_url: str
    reason: str | None = None
    lines: list[BuyLine] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        out = {"ok": 0, "out_of_stock": 0, "not_found": 0}
        for ln in self.lines:
            out[ln.status] = out.get(ln.status, 0) + 1
        return out


def buy_list(
    design: Design,
    library: Library,
    inventory: Union[Mapping[str, InventoryEntry], Iterable[InventoryEntry]],
    client: JlcpcbClient | None = None,
) -> BuyList:
    """Never raises for an unreachable API: `available=False` plus a reason,
    with the shortfalls still listed so the caller can source them by hand."""
    client = client or JlcpcbClient()
    report = check_inventory(design, library, inventory)
    out = BuyList(design_id=report.design_id, available=True, api_url=client.base_url)

    wanted: list[tuple[str, str, str, int, list[str], str]] = []
    for ln in report.lines:
        if ln.subcircuit or ln.status not in ("need", "partial"):
            continue
        wanted.append((ln.name, ln.kind, "", ln.needed - ln.on_hand, ln.instances, ln.library_id))
    for ln in report.parts:
        if ln.status not in ("need", "partial"):
            continue
        query = ln.value if ln.family in ("bjt", "mosfet", "transistor", "diode", "regulator", "ic") \
            else f"{ln.value} {ln.family}"
        wanted.append((ln.value, "part", ln.family, ln.needed - ln.on_hand, ln.refs, query))

    for label, kind, family, shortfall, refs, query in wanted:
        line = BuyLine(label=label, kind=kind, family=family, shortfall=shortfall,
                       refs=refs, query=query, status="not_found",
                       note="no JLCPCB match — source manually")
        if out.available:
            try:
                found = classify(query, label, query, shortfall, client.search(query))
            except JlcpcbUnavailable as exc:
                out.available, out.reason = False, str(exc)
            else:
                line.status, line.note = found.status, found.note
                if found.match is not None:
                    line.lcsc, line.mfr, line.package = found.match.lcsc, found.match.mfr, found.match.package
                    line.stock, line.price = found.match.stock, found.match.price
        if not out.available:
            line.note = "JLCPCB unavailable — source manually"
        out.lines.append(line)
    return out


def buy_list_to_dict(result: BuyList) -> dict:
    return {
        "design_id": result.design_id,
        "available": result.available,
        "api_url": result.api_url,
        "reason": result.reason,
        "summary": result.summary,
        "lines": [
            {
                "label": ln.label, "kind": ln.kind, "family": ln.family,
                "shortfall": ln.shortfall, "refs": ln.refs, "query": ln.query,
                "status": ln.status, "note": ln.note, "lcsc": ln.lcsc,
                "mfr": ln.mfr, "package": ln.package, "stock": ln.stock,
                "price": ln.price,
            }
            for ln in result.lines
        ],
    }
