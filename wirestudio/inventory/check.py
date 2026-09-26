"""Cross-check a design's BOM against the local inventory.

Groups the design into BOM parts the same way `ascii_gen` does -- a
component carrying module provenance collapses to one unit of its module
per distinct instance -- then compares each part's needed quantity
against what the inventory has on hand.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Optional, Union

from wirestudio.inventory.match import (
    family_for_ref,
    is_common,
    matches_by_value,
    normalize_value,
)
from wirestudio.inventory.store import InventoryEntry
from wirestudio.kicad.netlist import placed_parts
from wirestudio.library import Library, LibraryComponent, PartRequirements, part_value
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
    instances: list[str] = field(default_factory=list)
    subcircuit: bool = False  # built from parts; the parts report covers it


@dataclass
class Substitute:
    """A drawer part that could stand in for one the design calls for.
    Proposed, never applied: `caveats` says what was not compared.
    `headroom` is the candidate's rating over the circuit's need (v, i);
    `rank` orders proposals, 0 first: a known-matching pinout and
    package and at least 20% headroom on every compared rating beat
    the rest, and more on hand breaks ties."""
    mpn: str
    key: str
    on_hand: int
    location: str
    caveats: list[str]
    headroom: dict[str, Optional[float]] = field(default_factory=dict)
    rank: int = 0


MARGINAL_HEADROOM = 1.2


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
    substitutes: list[Substitute] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)  # part keys, for part_overrides
    substituted_for: list[str] = field(default_factory=list)


@dataclass
class PickItem:
    label: str  # component name, or the value printed on a part
    needed: int
    on_hand: int
    refs: list[str]  # designators, or component instance ids
    status: str
    inventory_key: str = ""


@dataclass
class PickGroup:
    """One place to go: a drawer location, or one of the three places a
    part can be when it is not in the drawer."""
    kind: str  # location | unlocated | assumed | missing
    location: str
    items: list[PickItem] = field(default_factory=list)


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

    @property
    def pick_list(self) -> list[PickGroup]:
        """What to pull, grouped by where it is. Drawer locations first,
        then stock with no recorded location, then common values nobody
        inventories, then what is missing. A component built from a
        subcircuit is covered by its parts and not listed twice;
        untracked designators (connectors) are not stock and are left out."""
        groups: dict[tuple[str, str], PickGroup] = {}

        def put(status: str, location: str, item: PickItem) -> None:
            if status in ("have", "partial"):
                key = ("location", location) if location else ("unlocated", "")
            elif status == "assumed":
                key = ("assumed", "")
            else:
                key = ("missing", "")
            groups.setdefault(key, PickGroup(kind=key[0], location=key[1])).items.append(item)

        for ln in self.lines:
            if ln.subcircuit:
                continue
            put(ln.status, ln.location, PickItem(
                label=ln.name, needed=ln.needed, on_hand=ln.on_hand,
                refs=ln.instances, status=ln.status, inventory_key=ln.library_id))
        for ln in self.parts:
            if ln.status == "untracked":
                continue
            put(ln.status, ln.location, PickItem(
                label=ln.value, needed=ln.needed, on_hand=ln.on_hand,
                refs=ln.refs, status=ln.status, inventory_key=ln.matched))
        order = {"location": 0, "unlocated": 1, "assumed": 2, "missing": 3}
        return sorted(groups.values(), key=lambda g: (order[g.kind], g.location.lower()))


def _bom_parts(design: Design) -> list[tuple[str, str, list[str]]]:
    """(kind, library_id, instance ids) per distinct BOM part, in design
    order. A module counts once per insertion, under its instance id."""
    instances: dict[tuple[str, str], list[str]] = {}
    seen_instances: set[str] = set()
    for comp in design.components:
        mod = comp.module
        if mod is not None:
            if mod.instance in seen_instances:
                continue
            seen_instances.add(mod.instance)
            key, ident = ("module", mod.module_id), mod.instance
        else:
            key, ident = ("component", comp.library_id), comp.id
        instances.setdefault(key, []).append(ident)
    return [(kind, lid, ids) for (kind, lid), ids in instances.items()]


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
    for kind, library_id, instances in _bom_parts(design):
        needed = len(instances)
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
            instances=instances,
            subcircuit=kind == "component" and _has_subcircuit(library, library_id),
        ))
    return report


def _has_subcircuit(library: Library, library_id: str) -> bool:
    try:
        return library.component(library_id).subcircuit is not None
    except FileNotFoundError:
        return False


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
    drawer = _Drawer(inventory)

    # (family, match key) -> [value as printed, refs, part keys, originals]
    groups: dict[tuple[str, str], tuple[str, list[str], list[str], list[str]]] = {}
    requirements: dict[tuple[str, str], list[PartRequirements]] = {}
    footprints: dict[tuple[str, str], str] = {}

    def add(family: str, value: str, ref: str, key: str = "", original: str = "") -> tuple[str, str]:
        group = (family, _group_key(family, value))
        slot = groups.setdefault(group, (value, [], [], []))
        slot[1].append(ref)
        if key:
            slot[2].append(key)
        if original and original not in slot[3]:
            slot[3].append(original)
        return group

    for part in placed_parts(design, library):
        if not part.part_id:
            continue  # the component's own symbol; the component check covers it
        value = getattr(part.kicad, "value", None) or ""
        if not value:
            continue
        group = add(family_for_ref(part.ref), value, part.ref, part.key, part.substituted_for)
        footprints.setdefault(group, part.kicad.footprint or "")
        spec = _part_spec(library, part.library_id, part.part_id)
        if spec is not None and spec.requires is not None:
            requirements.setdefault(group, []).append(spec.requires)

    for passive in design.passives:
        add(passive.kind, passive.value, passive.id)

    out: list[InventoryPartLine] = []
    for group, (value, refs, keys, originals) in groups.items():
        family, key = group
        needed = len(refs)
        if not family:
            out.append(InventoryPartLine(
                value=value, family="", refs=refs, needed=needed,
                on_hand=0, status="untracked", keys=keys, substituted_for=originals,
            ))
            continue
        entry = drawer.lookup(family, key)
        on_hand = entry.quantity if entry else 0
        status = _status(family, value, needed, on_hand)
        line = InventoryPartLine(
            value=value, family=family, refs=refs, needed=needed,
            on_hand=on_hand, status=status,
            matched=entry.key if entry else "",
            location=entry.location if entry else "",
            keys=keys, substituted_for=originals,
        )
        if status in ("need", "partial") and not matches_by_value(family):
            line.substitutes = find_substitutes(
                value, drawer.parts,
                requires=_merge_requirements(requirements.get(group, [])),
                footprint=footprints.get(group, ""),
            )
        out.append(line)
    return sorted(out, key=lambda ln: (ln.family, ln.value))


def subcircuit_coverage(
    component: LibraryComponent,
    inventory: Union[Mapping[str, InventoryEntry], Iterable[InventoryEntry]],
) -> tuple[int, int]:
    """(parts on hand, parts tracked) for a component's subcircuit, before
    it is placed in any design. Common passives count as on hand; parts
    the drawer does not track (connectors) are left out of both."""
    if component is None or component.subcircuit is None:
        return (0, 0)
    drawer = _Drawer(inventory)
    groups: dict[tuple[str, str], tuple[str, int]] = {}
    for part in component.subcircuit.parts:
        family = family_for_ref(part.ref_prefix)
        value = part_value(part, {}, component.params_schema)
        if not family or not value:
            continue
        group = (family, _group_key(family, value))
        groups[group] = (value, groups.get(group, (value, 0))[1] + 1)
    covered = tracked = 0
    for (family, key), (value, needed) in groups.items():
        entry = drawer.lookup(family, key)
        on_hand = entry.quantity if entry else 0
        status = _status(family, value, needed, on_hand)
        covered += needed if status in ("have", "assumed") else on_hand
        tracked += needed
    return (covered, tracked)


class _Drawer:
    """Part entries indexed the two ways a board part matches them."""

    def __init__(
        self, inventory: Union[Mapping[str, InventoryEntry], Iterable[InventoryEntry]]
    ) -> None:
        entries = (
            list(inventory.values()) if isinstance(inventory, Mapping) else list(inventory)
        )
        self.parts = [e for e in entries if e.kind == "part"]
        self.by_mpn = {e.mpn.upper(): e for e in self.parts if e.mpn}
        self.by_value: dict[tuple[str, str], InventoryEntry] = {}
        for e in self.parts:
            magnitude = normalize_value(e.value, e.family)
            if magnitude is not None:
                self.by_value[(e.family, _canon(magnitude))] = e

    def lookup(self, family: str, key: str) -> Optional[InventoryEntry]:
        if matches_by_value(family):
            return self.by_value.get((family, key))
        return self.by_mpn.get(key)


def _group_key(family: str, value: str) -> str:
    if matches_by_value(family):
        magnitude = normalize_value(value, family)
        if magnitude is not None:
            return _canon(magnitude)
    return value.upper()


def _status(family: str, value: str, needed: int, on_hand: int) -> str:
    if on_hand >= needed:
        return "have"
    if on_hand > 0:
        return "partial"
    if is_common(normalize_value(value, family), family):
        return "assumed"
    return "need"


def _part_spec(library: Library, library_id: str, part_id: str):
    try:
        comp = library.component(library_id)
    except FileNotFoundError:
        return None
    if comp.subcircuit is None:
        return None
    return next((p for p in comp.subcircuit.parts if p.id == part_id), None)


def _merge_requirements(reqs: list[PartRequirements]) -> Optional[PartRequirements]:
    """The most demanding of several declarations for one MPN."""
    if not reqs:
        return None
    v = [r.v_min for r in reqs if r.v_min is not None]
    i = [r.i_min for r in reqs if r.i_min is not None]
    return PartRequirements(
        family=reqs[0].family, polarity=reqs[0].polarity,
        v_min=max(v) if v else None, i_min=max(i) if i else None,
    )


# Footprint name fragment -> the package a drawer records. Anything else
# leaves the package unknown and substitution says so.
_PACKAGES = ("TO-220", "TO-247", "TO-252", "TO-92", "TO-126", "SOT-23", "SOT-223", "SOT-89")


def package_for_footprint(footprint: str) -> str:
    upper = (footprint or "").upper()
    return next((pkg for pkg in _PACKAGES if pkg in upper), "")


NOT_COMPARED = {
    "mosfet": "gate threshold and Rds(on) not compared",
    "bjt": "gain and saturation voltage not compared",
    "diode": "forward voltage and recovery time not compared",
}


def find_substitutes(
    mpn: str,
    parts: Iterable[InventoryEntry],
    *,
    requires: Optional[PartRequirements] = None,
    footprint: str = "",
) -> list[Substitute]:
    """Drawer parts that could stand in for `mpn`.

    Hard constraints: same family and polarity, same package (from the
    board footprint when it names one), voltage and current ratings at
    least what the circuit asks. The ask comes from `requires` when the
    library declares it; otherwise from the ratings of `mpn`'s own
    drawer entry, which is conservative and is called out as a caveat.
    A candidate whose rating is unrecorded fails rather than passes.
    Anything this does not compare is listed in each substitute's
    caveats. Nothing here is a verdict.
    """
    parts = [e for e in parts if e.kind == "part" and e.mpn]
    original = next((e for e in parts if e.mpn.upper() == mpn.upper()), None)
    if requires is not None:
        family, polarity = requires.family, requires.polarity
        v_min, i_min = requires.v_min, requires.i_min
        basis = ""
    elif original is not None and original.family:
        family, polarity = original.family, original.polarity
        v_min, i_min = original.v_max, original.i_max
        basis = f"ratings compared against {original.mpn}'s own, not the circuit's need"
    else:
        return []

    package = package_for_footprint(footprint) or (original.package if original else "")
    pinout = original.pinout if original else ""

    out: list[Substitute] = []
    for e in parts:
        if e.mpn.upper() == mpn.upper() or e.quantity <= 0:
            continue
        if e.family != family or (polarity and e.polarity != polarity):
            continue
        if package and e.package and e.package.upper() != package.upper():
            continue
        if v_min is not None and (e.v_max is None or e.v_max < v_min):
            continue
        if i_min is not None and (e.i_max is None or e.i_max < i_min):
            continue
        caveats: list[str] = []
        if package and not e.package:
            caveats.append("package not recorded")
        if pinout and e.pinout and e.pinout.upper() != pinout.upper():
            caveats.append(f"pinout {e.pinout} differs from {pinout}")
        headroom = {
            "v": (e.v_max / v_min) if v_min and e.v_max is not None else None,
            "i": (e.i_max / i_min) if i_min and e.i_max is not None else None,
        }
        # Against the original's own rating every candidate sits near 1.0x, so
        # "marginal" only means something when the circuit stated its need.
        marginal = [] if basis else [k for k, r in headroom.items() if r is not None and r < MARGINAL_HEADROOM]
        if marginal:
            caveats.append(
                "marginal " + " and ".join("voltage" if k == "v" else "current" for k in marginal)
                + " headroom (under 20%)"
            )
        if basis:
            caveats.append(basis)
        caveats.append(NOT_COMPARED.get(
            family, "only family, polarity, package and ratings compared"))
        out.append(Substitute(
            mpn=e.mpn, key=e.key, on_hand=e.quantity,
            location=e.location, caveats=caveats, headroom=headroom,
        ))
    ordered = sorted(out, key=lambda sub: (
        any(c.startswith("pinout ") for c in sub.caveats),
        "package not recorded" in sub.caveats,
        any(c.startswith("marginal ") for c in sub.caveats),
        -sub.on_hand,
        sub.mpn,
    ))
    for rank, sub in enumerate(ordered):
        sub.rank = rank
    return ordered


def apply_substitutions(
    design: Design, parts: Iterable[InventoryPartLine],
) -> tuple[Design, list[dict]]:
    """Accept the best-ranked substitute on every short semiconductor line
    at once: `part_overrides[key] = mpn` for each of the line's keys.
    Returns the updated design and what was applied, one entry per line.
    Lines without keys (design passives) or without a proposal are left
    alone; a line already overridden to its best proposal is not
    repeated."""
    overrides = dict(design.part_overrides)
    applied: list[dict] = []
    for line in parts:
        if line.status not in ("need", "partial") or not line.keys or not line.substitutes:
            continue
        best = line.substitutes[0]
        keys = [k for k in line.keys if overrides.get(k) != best.mpn]
        if not keys:
            continue
        for k in keys:
            overrides[k] = best.mpn
        applied.append({
            "value": line.value, "mpn": best.mpn, "keys": keys,
            "refs": list(line.refs), "caveats": list(best.caveats),
        })
    return design.model_copy(update={"part_overrides": overrides}), applied
