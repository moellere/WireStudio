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

from wirestudio.inventory.match import (
    family_for_ref,
    is_common,
    matches_by_value,
    normalize_value,
)
from wirestudio.inventory.store import InventoryEntry
from wirestudio.kicad.netlist import placed_parts
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
class InventoryPartLine:
    """One discrete part the board carries: a subcircuit part or a
    design passive, grouped by what you would buy."""
    value: str  # as printed on the board ("IRF4905", "10k")
    family: str
    refs: list[str]
    needed: int
    on_hand: int
    status: str  # have | partial | need | assumed | untracked
    matched: str = ""  # inventory key that satisfied it
    location: str = ""


@dataclass
class InventoryReport:
    design_id: str
    lines: list[InventoryLine] = field(default_factory=list)
    parts: list[InventoryPartLine] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        out = {"have": 0, "partial": 0, "need": 0}
        for ln in self.lines:
            out[ln.status] = out.get(ln.status, 0) + 1
        return out

    @property
    def parts_summary(self) -> dict[str, int]:
        out = {"have": 0, "partial": 0, "need": 0, "assumed": 0, "untracked": 0}
        for ln in self.parts:
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
    entries = (
        list(inventory.values()) if isinstance(inventory, Mapping) else list(inventory)
    )
    # Keyed by `key`, not library_id: every part entry has an empty
    # library_id and they would all collide on one slot.
    by_key = {e.key: e for e in entries}

    report = InventoryReport(design_id=design.id or "design")
    report.parts = check_parts(design, library, entries)
    for kind, library_id, needed in _bom_parts(design):
        entry = by_key.get(library_id)
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


def _canon(value: float) -> str:
    """Stable key for a magnitude, so 0.1uF and 100nF land together."""
    return f"{value:.6g}"


def check_parts(
    design: Design,
    library: Library,
    inventory: Union[Mapping[str, InventoryEntry], Iterable[InventoryEntry]],
) -> list[InventoryPartLine]:
    """Discrete parts the board carries, against the drawer.

    Covers what the component-level check cannot see: the parts a
    `subcircuit:` component expands into, and the design's own
    `passives`. Semiconductors match an inventory part by MPN, passives
    by magnitude.
    """
    entries = (
        list(inventory.values()) if isinstance(inventory, Mapping) else list(inventory)
    )
    parts_only = [e for e in entries if e.kind == "part"]
    by_mpn = {e.mpn.upper(): e for e in parts_only if e.mpn}
    by_value: dict[tuple[str, str], InventoryEntry] = {}
    for e in parts_only:
        magnitude = normalize_value(e.value, e.family)
        if magnitude is not None:
            by_value[(e.family, _canon(magnitude))] = e

    # (family, match key) -> [value as printed, refs]
    groups: dict[tuple[str, str], tuple[str, list[str]]] = {}

    def add(family: str, value: str, ref: str) -> None:
        if matches_by_value(family):
            magnitude = normalize_value(value, family)
            key = _canon(magnitude) if magnitude is not None else value.upper()
        else:
            key = value.upper()
        slot = groups.setdefault((family, key), (value, []))
        slot[1].append(ref)

    for part in placed_parts(design, library):
        if not part.part_id:
            continue  # the component's own symbol; the component check covers it
        value = getattr(part.kicad, "value", None) or ""
        if not value:
            continue
        add(family_for_ref(part.ref), value, part.ref)

    for passive in design.passives:
        add(passive.kind, passive.value, passive.id)

    out: list[InventoryPartLine] = []
    for (family, key), (value, refs) in groups.items():
        needed = len(refs)
        if not family:
            out.append(InventoryPartLine(
                value=value, family="", refs=refs, needed=needed,
                on_hand=0, status="untracked",
            ))
            continue
        entry = (
            by_value.get((family, key))
            if matches_by_value(family)
            else by_mpn.get(key)
        )
        on_hand = entry.quantity if entry else 0
        if on_hand >= needed:
            status = "have"
        elif on_hand > 0:
            status = "partial"
        elif is_common(normalize_value(value, family), family):
            status = "assumed"
        else:
            status = "need"
        out.append(InventoryPartLine(
            value=value, family=family, refs=refs, needed=needed,
            on_hand=on_hand, status=status,
            matched=entry.key if entry else "",
            location=entry.location if entry else "",
        ))
    return sorted(out, key=lambda ln: (ln.family, ln.value))
