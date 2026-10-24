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

from wirestudio.library import component_footprint, part_value
from wirestudio.migrate import load_design
from wirestudio.model import Design

_PY_IDENT_RE = re.compile(r"[^A-Za-z0-9_]")

# The dev board sits at the top of the schematic/board as M1; this key stands
# in for it in a ref map (component ids never collide with it).
BOARD_REF = "M1"
BOARD_KEY = "__board__"

# Reference-designator prefix per component category. Anything unlisted (and
# any component without a `kicad:` block) falls back to "U".
_REF_PREFIX = {
    "connector": "J",
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
            kicad = lib_comp.kicad if lib_comp is not None else None
            if kicad is not None and kicad.footprint and "{{" in kicad.footprint:
                kicad = kicad.model_copy(update={"footprint": component_footprint(lib_comp, c.params)})
            out.append(PlacedPart(
                key=c.id, ref=refs[c.id], component_id=c.id, library_id=c.library_id,
                part_id=None, kicad=kicad,
                name=lib_comp.name if lib_comp is not None else c.library_id,
            ))
            continue
        for part in sub.parts:
            key = part_key(c.id, part.id)
            kicad, original = part.kicad, ""
            value = part_value(part, c.params, lib_comp.params_schema)
            if value != kicad.value:
                kicad = kicad.model_copy(update={"value": value})
            mpn = design.part_overrides.get(key)
            if mpn and mpn != value:
                kicad, original = kicad.model_copy(update={"value": mpn}), value
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


# The bus line a library pin kind lands on. UART kinds name the part's own
# pin, so they cross over: the part's TX is the MCU's RX line.
_BUS_LINE = {
    "i2c_sda": "sda", "i2c_scl": "scl",
    "spi_clk": "clk", "spi_miso": "miso", "spi_mosi": "mosi", "spi_cs": "cs",
    "uart_tx": "rx", "uart_rx": "tx",
    "i2s_lrclk": "lrclk", "i2s_bclk": "bclk",
    "onewire_data": "pin",
}


def bus_net_name(bus_id: str, line: str | None) -> str:
    """One net per bus line, ``BUS_<id>_<LINE>``; a 1-wire bus is one line,
    ``BUS_<id>``, as is a pin whose kind names no line."""
    if line is None or line == "pin":
        return f"BUS_{bus_id}"
    return f"BUS_{bus_id}_{line.upper()}"


def _bus_line(design: Design | None, library, component_id: str, role: str) -> str | None:
    if design is None or library is None:
        return None
    comp = next((c for c in design.components if c.id == component_id), None)
    if comp is None:
        return None
    try:
        pins = library.component(comp.library_id).electrical.pins
    except FileNotFoundError:
        return None
    kind = next((p.kind for p in pins if p.role == role), None)
    return _BUS_LINE.get(kind)


def connection_net_name(conn, design: Design, library) -> str:
    """The net a design connection lands on: ``net_name`` of its target,
    with a bus target narrowed to the line the pin's kind names."""
    if conn.target.kind == "bus":
        return bus_net_name(conn.target.bus_id or "UNBOUND",
                            _bus_line(design, library, conn.component_id, conn.pin_role))
    return net_name(conn.target, design, library)


def net_name(target, design: Design | None = None, library=None) -> str:
    """Canonical net name for a connection target. Used verbatim in the PCB's
    ``(net ...)`` declarations and pad bindings, and as the inline SKiDL net
    name for gpio/expander/component targets, so both artifacts share names.

    rails -> ``GND`` / ``+5V`` / ``+3V3``; bus -> ``BUS_<id>`` (a
    connection's line comes from ``connection_net_name``);
    gpio -> ``GPIO_<pin>``; expander_pin -> ``<expander>_GP<n>``;
    component (hub) -> ``<component>_HUB``; net -> whatever
    ``resolve_net_target`` finds, which needs the design, else ``UNCONNECTED``.
    """
    kind = target.kind
    if kind == "net":
        if design is None:
            return "UNCONNECTED"
        return resolve_net_target(target, design, library) or "UNCONNECTED"
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
                role_nets[(conn.component_id, conn.pin_role)] = connection_net_name(conn, design, library)
            continue
        ref = refs.get(conn.component_id)
        if ref is None:
            continue
        if conn.target.kind == "net":
            # A passthrough pin pointing at nothing lands on no net at all
            # rather than on a shared "unconnected" one.
            name = resolve_net_target(conn.target, design, library)
            if name is None:
                continue
        else:
            name = connection_net_name(conn, design, library)
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
    board_pins, _ = board_bindings(design, library)
    for bp in board_pins:
        name = bp.net
        net = by_name.setdefault(name, Net(name=name))
        net.pads.append(NetPad(ref=refs[BOARD_KEY], component_id=BOARD_KEY, pin_role=bp.pin))
    return [by_name[n] for n in sorted(by_name)]


_BUS_PINS = ("sda", "scl", "clk", "miso", "mosi", "cs", "rx", "tx", "lrclk", "bclk", "pin")


@dataclass(frozen=True)
class BoardPin:
    """One board symbol pin, the connection target whose net it joins, and
    that net's name."""
    pin: str
    role: str
    target: object
    net: str


def board_bindings(design: Design, library) -> tuple[list[BoardPin], list[str]]:
    """Which board symbol pins join which nets: every bound gpio and rail
    target in the design's connections, plus the board GPIOs each bus runs
    on (the bus's own pins, else the board's default bus of that type). The
    roles come from the design (``GPIO13``, ``D2``, ``3V3``) and the board's
    ``kicad.pin_map`` turns them into symbol pin names.

    The second item lists what could not be placed, for the artifact to note:
    a role the pin_map lacks (a module symbol has no 5V pin), or a board with
    no pin_map at all, whose pins stay unconnected as before."""
    try:
        board = library.board(design.board.library_id)
    except FileNotFoundError:
        return [], []
    kicad = board.kicad
    if kicad is None:
        return [], []
    if not kicad.pin_map:
        return [], [
            f"board {board.id}: no kicad.pin_map, so its pins are left unconnected "
            f"(add one to library/boards/{board.id}.yaml)"
        ]
    buses = {b.id: b for b in design.buses}
    wanted: dict[str, tuple[object, str]] = {}
    for conn in design.connections:
        t = conn.target
        if not is_bound(t):
            continue
        if t.kind == "gpio":
            wanted.setdefault(t.pin, (t, net_name(t)))
        elif t.kind == "rail":
            role = "GND" if t.rail.lower() in ("gnd", "ground") else t.rail
            wanted.setdefault(role, (t, net_name(t)))
        elif t.kind == "bus":
            bus = buses.get(t.bus_id)
            if bus is None:
                continue
            defaults = board.default_buses.get(bus.type) or {}
            for name in _BUS_PINS:
                gpio = getattr(bus, name, None) or defaults.get(name)
                if gpio:
                    wanted.setdefault(gpio, (t, bus_net_name(bus.id, name)))
    pins: list[BoardPin] = []
    notes: list[str] = []
    for role, (target, net) in wanted.items():
        pin = kicad.pin_map.get(role)
        if pin is None:
            notes.append(
                f"{role}: no pin on {kicad.symbol_lib}:{kicad.symbol} "
                f"(board {board.id} pin_map)"
            )
            continue
        pins.append(BoardPin(pin=pin, role=role, target=target, net=net))
    return pins, notes


def is_bound(target) -> bool:
    """False for a gpio / bus target the pin solver hasn't filled in yet, or a
    net target nobody has pointed at a component yet."""
    if target.kind == "gpio":
        return bool(target.pin)
    if target.kind == "bus":
        return bool(target.bus_id)
    if target.kind == "net":
        return bool(target.component_id and target.net)
    return True


def resolve_net_target(target, design: Design, library, _seen: tuple = ()) -> str | None:
    """The canonical net a ``net`` target lands on, or None when it points at
    nothing: the net the named component's role ``net`` is wired to (through
    further net targets if need be), else, for a subcircuit component, the
    instance-local net of the internal node or unconnected role so named."""
    if not is_bound(target):
        return None
    key = (target.component_id, target.net)
    if key in _seen:
        return None
    comp = next((c for c in design.components if c.id == target.component_id), None)
    if comp is None:
        return None
    for conn in design.connections:
        if conn.component_id == comp.id and conn.pin_role == target.net:
            if not is_bound(conn.target):
                return None
            if conn.target.kind == "net":
                return resolve_net_target(conn.target, design, library, _seen + (key,))
            return connection_net_name(conn, design, library)
    sub = _subcircuit(comp, library) if library is not None else None
    if sub is not None and any(target.net in part.pins.values() for part in sub.parts):
        return local_net_name(comp.id, target.net)
    return None


def format_netlist(design: Design, library) -> str:
    """One line per net, ``<name>: <ref>.<pin>, ...`` in pad order. The
    shape the netlist goldens pin."""
    return "\n".join(
        f"{net.name}: " + ", ".join(f"{p.ref}.{p.pin_role}" for p in net.pads)
        for net in build_netlist(design, library)
    ) + "\n"


def main(argv: list[str] | None = None) -> int:
    """``python -m wirestudio.kicad.netlist design.json`` prints the netlist
    in golden form."""
    import argparse
    import json
    import sys

    from wirestudio.library import default_library

    parser = argparse.ArgumentParser(description="Print a design's netlist, one net per line.")
    parser.add_argument("design", help="path to design.json")
    args = parser.parse_args(argv)
    with open(args.design) as fh:
        design = load_design(json.load(fh))
    sys.stdout.write(format_netlist(design, default_library()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
