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


def assign_refs(design: Design, library) -> dict[str, str]:
    """Map each component id -> KiCad reference designator, plus ``BOARD_KEY``
    -> ``BOARD_REF``. Allocation order matches the schematic exactly: board
    first, then components in design order, with a per-prefix counter."""
    refs: dict[str, str] = {BOARD_KEY: BOARD_REF}
    counter: dict[str, int] = {}
    for c in design.components:
        prefix = _REF_PREFIX.get(_category_for(c, library), "U")
        counter[prefix] = counter.get(prefix, 0) + 1
        refs[c.id] = f"{prefix}{counter[prefix]}"
    return refs


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
    KiCad symbol/footprint happens in the PCB emitter, not here."""
    ref: str
    component_id: str
    pin_role: str


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
    for conn in design.connections:
        ref = refs.get(conn.component_id)
        if ref is None:
            continue
        name = net_name(conn.target)
        net = by_name.setdefault(name, Net(name=name))
        net.pads.append(
            NetPad(ref=ref, component_id=conn.component_id, pin_role=conn.pin_role)
        )
    return [by_name[n] for n in sorted(by_name)]
