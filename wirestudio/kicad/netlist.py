"""Shared schematic/PCB netlist primitives: reference-designator assignment
and canonical net names.

Both the SKiDL schematic emitter (``wirestudio.kicad.generator``) and the
``.kicad_pcb`` emitter (``wirestudio.kicad.pcb``) build on these so the two
artifacts agree on reference designators (U1, D1, M1) and on net names for the
same design. Pure: no I/O, no library mutation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from wirestudio.model import Design

_PY_IDENT_RE = re.compile(r"[^A-Za-z0-9_]")

# The dev board sits at the top of the schematic/board as M1; this key stands
# in for it in a ref map (component ids never collide with it).
BOARD_REF = "M1"
BOARD_KEY = "__board__"

# Reference-designator prefix per component category. Anything unlisted (and
# any component without a `kicad:` block) falls back to "U".
_REF_PREFIX = {
    "sensor": "U",
    "binary_sensor": "U",
    "io_expander": "U",
    "display": "U",
    "audio": "U",
    "led": "D",
    "amp": "U",
}


def _py_var(name: str) -> str:
    """Coerce an arbitrary id into a safe Python identifier; callers prefix
    it with ``c_`` (component) or ``n_`` (net)."""
    out = _PY_IDENT_RE.sub("_", name)
    if out and out[0].isdigit():
        out = "_" + out
    return out


def _category_for(c, library) -> str:
    """The category that drives a component's ref prefix. A component with no
    library entry or no ``kicad:`` block is treated as a generic ``sensor``
    (prefix U) -- the same fallback the schematic placeholder uses."""
    try:
        lib_comp = library.component(c.library_id)
    except FileNotFoundError:
        return "sensor"
    if lib_comp.kicad is None:
        return "sensor"
    return lib_comp.category


def _subcircuit(c, library):
    try:
        return library.component(c.library_id).subcircuit
    except FileNotFoundError:
        return None


def part_key(component_id: str, part_id: str) -> str:
    """Ref-map key for one part of a component's subcircuit."""
    return f"{component_id}.{part_id}"


def assign_refs(design: Design, library) -> dict[str, str]:
    """Map each component id -> KiCad reference designator, plus ``BOARD_KEY``
    -> ``BOARD_REF``. Allocation order matches the schematic exactly: board
    first, then components in design order, with a per-prefix counter.

    A component with a ``subcircuit`` has no designator of its own; each of
    its parts gets one under ``part_key(component_id, part_id)``."""
    refs: dict[str, str] = {BOARD_KEY: BOARD_REF}
    counter: dict[str, int] = {}

    def take(prefix: str) -> str:
        counter[prefix] = counter.get(prefix, 0) + 1
        return f"{prefix}{counter[prefix]}"

    for c in design.components:
        sub = _subcircuit(c, library)
        if sub is None:
            refs[c.id] = take(_REF_PREFIX.get(_category_for(c, library), "U"))
            continue
        for part in sub.parts:
            refs[part_key(c.id, part.id)] = take(part.ref_prefix)
    return refs


@dataclass(frozen=True)
class PlacedPart:
    """One symbol/footprint the KiCad artifacts emit: either a component's own
    ``kicad:`` mapping (``part_id`` None, ``kicad`` None when unmapped) or one
    part of its subcircuit."""
    key: str
    ref: str
    component_id: str
    library_id: str
    part_id: str | None
    kicad: object | None
    name: str
    substituted_for: str = ""  # the library value a part_override replaced


def placed_parts(design: Design, library) -> list[PlacedPart]:
    """Every part the schematic, PCB, BOM and CPL emit for the design's
    components, in ref-allocation order. The board is not included."""
    refs = assign_refs(design, library)
    out: list[PlacedPart] = []
    for c in design.components:
        try:
            lib_comp = library.component(c.library_id)
        except FileNotFoundError:
            lib_comp = None
        sub = lib_comp.subcircuit if lib_comp is not None else None
        if sub is None:
            out.append(PlacedPart(
                key=c.id, ref=refs[c.id], component_id=c.id, library_id=c.library_id,
                part_id=None, kicad=lib_comp.kicad if lib_comp is not None else None,
                name=lib_comp.name if lib_comp is not None else c.library_id,
            ))
            continue
        for part in sub.parts:
            key = part_key(c.id, part.id)
            kicad, original = part.kicad, ""
            mpn = design.part_overrides.get(key)
            if mpn and mpn != kicad.value:
                kicad, original = kicad.model_copy(update={"value": mpn}), kicad.value or ""
            out.append(PlacedPart(
                key=key, ref=refs[key], component_id=c.id, library_id=c.library_id,
                part_id=part.id, kicad=kicad, name=f"{lib_comp.name}: {part.id}",
                substituted_for=original,
            ))
    return out


def local_net_name(component_id: str, name: str) -> str:
    """Net local to one subcircuit instance: an internal node, or a host pin
    role the design leaves unconnected (a motor output, say)."""
    return f"{_py_var(component_id)}_{name}"


def net_name(target) -> str:
    """Canonical net name for a connection target. Used verbatim in the PCB's
    ``(net ...)`` declarations and pad bindings, and as the inline SKiDL net
    name for gpio/expander/component targets, so both artifacts share names.

    rails -> ``GND`` / ``+5V`` / ``+3V3``; bus -> ``BUS_<id>``;
    gpio -> ``GPIO_<pin>``; expander_pin -> ``<expander>_GP<n>``;
    component (hub) -> ``<component>_HUB``.
    """
    kind = target.kind
    if kind == "rail":
        if target.rail.lower() in ("gnd", "ground"):
            return "GND"
        return f"+{target.rail}"
    if kind == "bus":
        return f"BUS_{target.bus_id or 'UNBOUND'}"
    if kind == "gpio":
        return f"GPIO_{_py_var(target.pin or 'UNBOUND')}"
    if kind == "expander_pin":
        return f"{target.expander_id or 'EX'}_GP{target.number}"
    if kind == "component":
        return f"{target.component_id or 'PARENT'}_HUB"
    return "UNCONNECTED"


@dataclass(frozen=True)
class NetPad:
    """One landing of a net: a component's reference designator plus the
    design pin role to bind. The role -> pad-number resolution against the
    KiCad symbol/footprint happens in the PCB emitter, not here.

    For a subcircuit part ``part_id`` is set and ``pin_role`` holds the part
    symbol's pin name or number rather than a component role."""
    ref: str
    component_id: str
    pin_role: str
    part_id: str | None = None


@dataclass
class Net:
    name: str
    pads: list[NetPad] = field(default_factory=list)


def build_netlist(design: Design, library) -> list[Net]:
    """Group the design's connections into nets, keyed by canonical
    ``net_name``. Mirrors the schematic's net derivation exactly (same
    ``assign_refs`` + ``net_name``), so the schematic and the PCB land the
    same pads on the same nets. Connections to a component not in the design
    are skipped. Nets are returned sorted by name, pads in connection order,
    for stable, diffable output."""
    refs = assign_refs(design, library)
    by_name: dict[str, Net] = {}
    subcircuits = {
        c.id: sub for c in design.components
        if (sub := _subcircuit(c, library)) is not None
    }
    role_nets: dict[tuple[str, str], str] = {}
    for conn in design.connections:
        if conn.component_id in subcircuits:
            if is_bound(conn.target):
                role_nets[(conn.component_id, conn.pin_role)] = net_name(conn.target)
            continue
        ref = refs.get(conn.component_id)
        if ref is None:
            continue
        name = net_name(conn.target)
        net = by_name.setdefault(name, Net(name=name))
        net.pads.append(
            NetPad(ref=ref, component_id=conn.component_id, pin_role=conn.pin_role)
        )
    for comp_id, sub in subcircuits.items():
        for part in sub.parts:
            ref = refs[part_key(comp_id, part.id)]
            for pin, node in part.pins.items():
                name = role_nets.get((comp_id, node)) or local_net_name(comp_id, node)
                net = by_name.setdefault(name, Net(name=name))
                net.pads.append(
                    NetPad(ref=ref, component_id=comp_id, pin_role=pin, part_id=part.id)
                )
    return [by_name[n] for n in sorted(by_name)]


def is_bound(target) -> bool:
    """False for a gpio / bus target the pin solver hasn't filled in yet."""
    if target.kind == "gpio":
        return bool(target.pin)
    if target.kind == "bus":
        return bool(target.bus_id)
    return True
