"""Cross-check a design's BOM against the local inventory.

Groups the design into BOM parts the same way `ascii_gen` does -- a
component carrying module provenance collapses to one unit of its module
per distinct instance -- then compares each part's needed quantity
against what the inventory has on hand.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Union

from wirestudio.inventory.store import InventoryEntry
from wirestudio.library import Library
from wirestudio.model import Design


@dataclass
class InventoryLine:
    library_id: str
    kind: str  # component | module
    name: str
    needed: int
    on_hand: int
    status: str  # have | partial | need
    location: str = ""
    note: str = ""


@dataclass
class InventoryReport:
    design_id: str
    lines: list[InventoryLine] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        out = {"have": 0, "partial": 0, "need": 0}
        for ln in self.lines:
            out[ln.status] = out.get(ln.status, 0) + 1
        return out


def _bom_parts(design: Design) -> list[tuple[str, str, int]]:
    """(kind, library_id, quantity) per distinct BOM part, in design order."""
    counts: dict[tuple[str, str], int] = {}
    order: list[tuple[str, str]] = []
    seen_instances: set[str] = set()
    for comp in design.components:
        mod = comp.module
        if mod is not None:
            if mod.instance in seen_instances:
                continue
            seen_instances.add(mod.instance)
            key = ("module", mod.module_id)
        else:
            key = ("component", comp.library_id)
        if key not in counts:
            order.append(key)
        counts[key] = counts.get(key, 0) + 1
    return [(kind, lid, counts[(kind, lid)]) for kind, lid in order]


def _name(library: Library, kind: str, library_id: str) -> str:
    try:
        if kind == "module":
            return library.module(library_id).name
        return library.component(library_id).name
    except FileNotFoundError:
        return library_id


def check_inventory(
    design: Design,
    library: Library,
    inventory: Union[Mapping[str, InventoryEntry], Iterable[InventoryEntry]],
) -> InventoryReport:
    """Compare the design BOM against `inventory`.

    `inventory` is a mapping of library id -> entry, or any iterable of
    entries. Each BOM part lands as `have` (enough on hand), `partial`
    (some, but short), or `need` (none).
    """
    if not isinstance(inventory, Mapping):
        inventory = {e.library_id: e for e in inventory}

    report = InventoryReport(design_id=design.id or "design")
    for kind, library_id, needed in _bom_parts(design):
        entry = inventory.get(library_id)
        on_hand = entry.quantity if entry else 0
        if on_hand >= needed:
            status = "have"
        elif on_hand > 0:
            status = "partial"
        else:
            status = "need"
        report.lines.append(InventoryLine(
            library_id=library_id,
            kind=kind,
            name=_name(library, kind, library_id),
            needed=needed,
            on_hand=on_hand,
            status=status,
            location=entry.location if entry else "",
            note=entry.note if entry else "",
        ))
    return report
