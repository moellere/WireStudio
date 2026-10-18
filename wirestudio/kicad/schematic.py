"""`.kicad_sch` writer: the design drawn as a KiCad 8 sheet.

The sheet is built, not placed by a solver: the board on the left, the
peripherals in columns beside it, and each subcircuit as a block --
drawn from the layout in its library entry when it has one, otherwise
its parts stacked. Every connected pin ends in a power symbol (rails) or
a global label carrying the net's name, every unconnected pin carries a
no-connect flag, and each rail gets one PWR_FLAG, so KiCad's ERC reads
the sheet the way a person would. Inside a laid-out block the pins are
joined by wires, with junctions where three meet.

Connectivity is the netlist in ``wirestudio.kicad.netlist``; the sheet is
only its drawing. ``scripts/check_sch.py`` has KiCad derive the netlist
back from the geometry and compares.

Symbols are embedded from the pinned KiCad library (``extends`` resolved),
so the file opens with no library setup. Output is deterministic: same
design + same library -> byte-identical sheet, UUIDs included.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from wirestudio.kicad.importer import default_symbol_dirs
from wirestudio.kicad.netlist import BOARD_KEY, assign_refs, build_netlist, local_net_name, placed_parts
from wirestudio.kicad.symbol_parser import (
    QStr, SymbolPin, dump_sexpr, embed_symbol, load_symbol_trees, symbol_bbox, symbol_pins,
)
from wirestudio.library import Library, SchematicLayout
from wirestudio.model import Design

GRID = 1.27
_NS = uuid.UUID("5b1f9c2e-6d1a-4c7b-9a35-7f0e3a2d8c41")

# A4 landscape, drawing area inside the frame; the title block takes the
# bottom-right corner, so columns stop short of its top and the rail
# flags sit bottom-left.
_PAGE = "A4"
_LEFT, _TOP = 15.24, 20.32
_BOTTOM = 160.0
_COL_GAP, _ROW_GAP = 8 * GRID, 6 * GRID
_STUB = 2 * GRID
_MAX_STACK = 110.0

_POWER_SYMBOLS = {"GND": "GND", "+5V": "+5V", "+3V3": "+3V3", "+12V": "+12V", "+24V": "+24V"}

Point = tuple[float, float]


class SchematicUnavailable(RuntimeError):
    """The KiCad symbol libraries are not on this machine."""


def sch_status() -> dict:
    dirs = [d for d in default_symbol_dirs() if d.is_dir()]
    return {
        "available": bool(dirs),
        "symbol_dir": str(dirs[0]) if dirs else None,
        "reason": None if dirs else "symbol libraries not found (set KICAD8_SYMBOL_DIR)",
    }


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def _r(v: float) -> float:
    return round(v, 4) + 0.0


def snap(v: float) -> float:
    return _r(round(v / GRID) * GRID)


def _xform(x: float, y: float, rot: int, mirror: Optional[str]) -> Point:
    """Symbol-space offset (mm, Y up) -> sheet offset (mm, Y down) for a
    symbol mirrored about an axis and then turned `rot` counter-clockwise."""
    if mirror == "y":
        x = -x
    elif mirror == "x":
        y = -y
    r = math.radians(rot)
    xr = x * math.cos(r) - y * math.sin(r)
    yr = x * math.sin(r) + y * math.cos(r)
    return (_r(xr), _r(-yr))


def _on_segment(p: Point, a: Point, b: Point) -> bool:
    """Strictly inside the axis-aligned segment a-b."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    if abs(ax - bx) < 1e-6:
        return abs(px - ax) < 1e-6 and min(ay, by) + 1e-6 < py < max(ay, by) - 1e-6
    if abs(ay - by) < 1e-6:
        return abs(py - ay) < 1e-6 and min(ax, bx) + 1e-6 < px < max(ax, bx) - 1e-6
    return False


def _power_rot(net: str, dx: int, dy: int) -> int:
    """The rotation that points a rail symbol's body along (dx, dy) on the
    sheet. GND hangs down from its pin, the others stand up."""
    body = (0.0, -1.0) if net == "GND" else (0.0, 1.0)
    for rot in (0, 90, 180, 270):
        bx, by = _xform(body[0], body[1], rot, None)
        if (int(round(bx)), int(round(by))) == (dx, dy):
            return rot
    return 0


@dataclass
class Symbol:
    """One symbol instance on the sheet, anchor at (x, y) mm."""
    ref: str
    lib: str
    name: str
    value: str
    footprint: str
    pins: list[SymbolPin]
    bbox: tuple[float, float, float, float]
    props: dict[str, tuple[float, float, int]]
    power: bool = False
    x: float = 0.0
    y: float = 0.0
    rot: int = 0
    mirror: Optional[str] = None

    @property
    def lib_id(self) -> str:
        return f"{self.lib}:{self.name}"

    def pin_at(self, pin: SymbolPin) -> Point:
        ox, oy = _xform(pin.x, pin.y, self.rot, self.mirror)
        return (_r(self.x + ox), _r(self.y + oy))

    def pin_out(self, pin: SymbolPin) -> tuple[int, int]:
        """Unit direction away from the body, on the sheet."""
        a = math.radians(pin.angle)
        dx, dy = _xform(-math.cos(a), -math.sin(a), self.rot, self.mirror)
        return (int(round(dx)), int(round(dy)))

    def extent(self) -> tuple[float, float, float, float]:
        """Sheet bbox of body and pins, relative to the anchor."""
        x0, y0, x1, y1 = self.bbox
        pts = [_xform(x, y, self.rot, self.mirror) for x in (x0, x1) for y in (y0, y1)]
        return (min(p[0] for p in pts), min(p[1] for p in pts),
                max(p[0] for p in pts), max(p[1] for p in pts))


class _Symbols:
    """Symbol library access, trees cached per file, one embedded copy
    per lib_id for the sheet's lib_symbols."""

    def __init__(self, sym_dir: Path) -> None:
        self.dir = sym_dir
        self._trees: dict[str, dict[str, list]] = {}
        self.embedded: dict[str, list] = {}

    def trees(self, lib: str) -> dict[str, list]:
        if lib not in self._trees:
            path = self.dir / f"{lib}.kicad_sym"
            if not path.is_file():
                raise FileNotFoundError(f"KiCad symbol library {lib!r} not found in {self.dir}")
            self._trees[lib] = load_symbol_trees(path)
        return self._trees[lib]

    def make(self, ref: str, lib: str, name: str, value: str, footprint: str = "", *, power: bool = False) -> Symbol:
        trees = self.trees(lib)
        if name not in trees:
            raise FileNotFoundError(f"no symbol {name!r} in KiCad library {lib}")
        lib_id = f"{lib}:{name}"
        if lib_id not in self.embedded:
            self.embedded[lib_id] = embed_symbol(trees, name, lib)
        el = self.embedded[lib_id]
        props: dict[str, tuple[float, float, int]] = {}
        for child in el[2:]:
            if isinstance(child, list) and child and child[0] == "property" and len(child) > 3:
                at = next((c for c in child if isinstance(c, list) and c and c[0] == "at"), None)
                if at is not None:
                    angle = int(float(at[3])) if len(at) > 3 else 0
                    props[str(child[1])] = (float(at[1]), float(at[2]), angle)
        return Symbol(
            ref=ref, lib=lib, name=name, value=value, footprint=footprint,
            pins=symbol_pins(el), bbox=symbol_bbox(el), props=props, power=power,
        )


def _pins_for(sym: Symbol, pin_role: str, lib_comp, positional: bool) -> list[SymbolPin]:
    """The symbol pins a netlist pad names: through the component's
    pin_map, then by name (every pin of that name -- a module's GNDs are
    one net), then by number; generic connectors bind positionally."""
    if positional and lib_comp is not None:
        roles = [p.role for p in lib_comp.electrical.pins]
        if pin_role in roles:
            pin_role = str(roles.index(pin_role) + 1)
    elif lib_comp is not None and lib_comp.kicad is not None:
        pin_role = lib_comp.kicad.pin_map.get(pin_role, pin_role)
    named = [p for p in sym.pins if p.name == pin_role]
    if named:
        return named
    return [p for p in sym.pins if p.number == pin_role]


# ---------------------------------------------------------------------------
# Sheet items
# ---------------------------------------------------------------------------

@dataclass
class Sheet:
    design_id: str
    title: str
    symbols: list[Symbol] = field(default_factory=list)
    wires: list[tuple[Point, Point]] = field(default_factory=list)
    labels: list[tuple[str, float, float, int]] = field(default_factory=list)
    junctions: list[Point] = field(default_factory=list)
    no_connects: list[Point] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    pin_nets: dict[tuple[str, str], str] = field(default_factory=dict)
    embedded: dict[str, list] = field(default_factory=dict)
    _pwr: int = 0

    def uid(self, key: str) -> str:
        return str(uuid.uuid5(_NS, f"{self.design_id}:{key}"))

    def wire(self, a: Point, b: Point) -> None:
        """Stacked pins (a module's GNDs) ask for the same stub more than
        once; one wire is drawn."""
        if a != b and (a, b) not in self.wires and (b, a) not in self.wires:
            self.wires.append((a, b))

    def polyline(self, pts: list[Point]) -> None:
        for a, b in zip(pts, pts[1:]):
            self.wire(a, b)

    def label(self, name: str, x: float, y: float, rot: int) -> None:
        self.labels.append((name, x, y, rot))

    def power(self, syms: _Symbols, net: str, x: float, y: float, rot: int) -> bool:
        """A power symbol for `net` with its pin at (x, y); False when the
        net has no power symbol (the caller labels it instead)."""
        name = _POWER_SYMBOLS.get(net)
        if name is None:
            return False
        self._pwr += 1
        s = syms.make(f"#PWR{self._pwr:03d}", "power", name, net, power=True)
        s.x, s.y, s.rot = x, y, rot
        self.symbols.append(s)
        return True

    def flag(self, syms: _Symbols, x: float, y: float) -> None:
        self._pwr += 1
        s = syms.make(f"#FLG{self._pwr:03d}", "power", "PWR_FLAG", "PWR_FLAG", power=True)
        s.x, s.y = x, y
        self.symbols.append(s)

    def terminate(self, syms: _Symbols, net: str, x: float, y: float, dx: int, dy: int) -> None:
        """End a pin at (x, y) facing (dx, dy) on a short stub: a rail off
        a vertical pin gets its power symbol, anything else a global label
        with the net's name. A rail label joins the rail's net by name;
        pins sit 2.54 mm apart, so a symbol lying sideways would cover
        the neighbour's label."""
        ex, ey = _r(x + dx * _STUB), _r(y + dy * _STUB)
        self.wire((x, y), (ex, ey))
        if net in _POWER_SYMBOLS and dy != 0:
            self.power(syms, net, ex, ey, _power_rot(net, dx, dy))
            return
        self.label(net, ex, ey, _LABEL_ROT.get((dx, dy), 0))


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

@dataclass
class Block:
    """A group drawn as one unit and packed onto the sheet. Coordinates
    inside are mm relative to the block origin; `w`, `h` include the room
    its labels take, `pad_*` how far the origin sits inside that room.
    `loose` is None for a stacked block (every pin is terminated) and the
    list of pins a layout's wires missed for a laid-out one."""
    key: str
    symbols: list[Symbol]
    w: float
    h: float
    pad_left: float = 0.0
    pad_top: float = 0.0
    wires: list[list[Point]] = field(default_factory=list)
    ports: list[tuple[str, float, float, str, int]] = field(default_factory=list)
    loose: Optional[list[tuple[Symbol, SymbolPin, str]]] = None


_LABEL_ROT = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}


def _label_room(name: str) -> float:
    return snap(len(name) * 1.1 * GRID + 4 * GRID)


def _stacked_block(key: str, syms: list[Symbol], pin_nets: dict[tuple[str, str], str]) -> Block:
    """Parts one above the other, every pin terminated outward."""
    y = 0.0
    left = right = 0.0
    for s in syms:
        x0, y0, x1, y1 = s.extent()
        room = {"l": _STUB + 2 * GRID, "r": _STUB + 2 * GRID, "t": 3 * GRID, "b": 3 * GRID}
        for p in s.pins:
            net = pin_nets.get((s.ref, p.number))
            if net is None:
                continue
            dx, dy = s.pin_out(p)
            side = "l" if dx < 0 else "r" if dx > 0 else "t" if dy < 0 else "b"
            if dy == 0:
                need = _STUB + _label_room(net)
            else:
                need = _STUB + (5 * GRID if net in _POWER_SYMBOLS else _label_room(net))
            room[side] = max(room[side], need)
        s.x, s.y = 0.0, snap(y + room["t"] - y0)
        y = s.y + y1 + room["b"] + _ROW_GAP
        left = min(left, x0 - room["l"])
        right = max(right, x1 + room["r"])
    return Block(key, syms, w=right - left, h=max(y - _ROW_GAP, GRID), pad_left=-left)


def _laid_out_block(
    key: str, layout: SchematicLayout, parts: dict[str, Symbol],
    node_nets: dict[str, str], part_pin_nodes: dict[str, dict[str, str]],
    internal: set[str], shared: set[str], notes: list[str],
) -> Block:
    """A block drawn from its library layout. A port on an `internal` node
    is drawn only when something outside the block uses the node
    (`shared`). Pins the layout's wires miss are terminated on their own,
    and a shared node without a port gets a label at one of its pins, so
    the drawing is never electrically short of the netlist."""
    syms: list[Symbol] = []
    for part_id, place in layout.parts.items():
        s = parts[part_id]
        s.x, s.y = _r(place.at[0] * GRID), _r(place.at[1] * GRID)
        s.rot, s.mirror = place.rot, place.mirror
        syms.append(s)
    wires = [[(_r(x * GRID), _r(y * GRID)) for x, y in pl] for pl in layout.wires]
    touched: set[Point] = set()
    for pl in wires:
        touched.update(pl)
    ports: list[tuple[str, float, float, str, int]] = []
    for node, plist in layout.nodes.items():
        if node in internal and node not in shared:
            continue
        net = node_nets.get(node)
        if net is None:
            notes.append(f"{key}: layout port for node {node!r}, which is not connected")
            continue
        for port in plist:
            ports.append((net, _r(port.at[0] * GRID), _r(port.at[1] * GRID), port.kind, port.rot))
    loose: list[tuple[Symbol, SymbolPin, str]] = []
    unported = sorted(shared - set(layout.nodes))
    for part_id, s in parts.items():
        if part_id not in layout.parts:
            continue
        for p in s.pins:
            node = part_pin_nodes[part_id].get(p.name) or part_pin_nodes[part_id].get(p.number)
            if node is None or node not in node_nets:
                continue
            if node in unported:
                unported.remove(node)
                x, y = s.pin_at(p)
                ports.append((node_nets[node], x, y, "label", _LABEL_ROT.get(s.pin_out(p), 0)))
                notes.append(f"{key}: node {node!r} is used outside the block and the layout has no port for it; labelled at {s.ref}.{p.number}")
            pt = s.pin_at(p)
            if pt in touched or any(_on_segment(pt, a, b) for pl in wires for a, b in zip(pl, pl[1:])):
                continue
            notes.append(f"{key}: pin {s.ref}.{p.number} ({node}) is not reached by a layout wire; labelled")
            loose.append((s, p, node_nets[node]))
    xs, ys = [0.0], [0.0]
    for s in syms:
        x0, y0, x1, y1 = s.extent()
        xs += [s.x + x0, s.x + x1]
        ys += [s.y + y0, s.y + y1]
    for pl in wires:
        for x, y in pl:
            xs.append(x)
            ys.append(y)
    for net, x, y, kind, rot in ports:
        room = _label_room(net) if kind == "label" else 5 * GRID
        if kind == "label":
            xs.append(x + room if rot == 0 else x - room if rot == 180 else x)
            ys.append(y - room if rot == 90 else y + room if rot == 270 else y)
        else:
            ys += [y - room, y + room]
    return Block(key, syms, w=max(xs) - min(xs), h=max(ys) - min(ys),
                 pad_left=-min(xs), pad_top=-min(ys), wires=wires, ports=ports, loose=loose)


# ---------------------------------------------------------------------------
# The sheet
# ---------------------------------------------------------------------------

def build_sheet(design: Design, library: Library, *, symbol_dir: Optional[Path] = None) -> Sheet:
    """Place and wire the design. Raises SchematicUnavailable without the
    symbol libraries, FileNotFoundError for a symbol the library lacks."""
    status = sch_status()
    sym_dir = Path(symbol_dir) if symbol_dir else (Path(status["symbol_dir"]) if status["symbol_dir"] else None)
    if sym_dir is None:
        raise SchematicUnavailable(status["reason"])
    syms = _Symbols(sym_dir)
    sheet = Sheet(design_id=design.id, title=design.name or design.id)
    refs = assign_refs(design, library)
    nets = build_netlist(design, library)
    parts = placed_parts(design, library)

    symbols: dict[str, Symbol] = {}
    lib_comps: dict[str, object] = {}
    try:
        board = library.board(design.board.library_id)
    except FileNotFoundError:
        board = None
    if board is not None and board.kicad is not None:
        symbols[BOARD_KEY] = syms.make(
            refs[BOARD_KEY], board.kicad.symbol_lib, board.kicad.symbol,
            board.kicad.value or board.name, board.kicad.footprint or "",
        )
    for part in parts:
        k = part.kicad
        if k is None:
            symbols[part.key] = syms.make(part.ref, "Connector_Generic", "Conn_01x04", part.library_id)
        else:
            symbols[part.key] = syms.make(part.ref, k.symbol_lib, k.symbol, k.value or k.symbol, k.footprint or "")
        try:
            lib_comps[part.component_id] = library.component(part.library_id)
        except FileNotFoundError:
            lib_comps[part.component_id] = None
    by_ref = {s.ref: s for s in symbols.values()}

    pin_nets = sheet.pin_nets
    for net in nets:
        for pad in net.pads:
            s = by_ref.get(pad.ref)
            if s is None:
                continue
            if pad.component_id == BOARD_KEY or pad.part_id is not None:
                pins = _pins_for(s, pad.pin_role, None, False)
            else:
                lc = lib_comps.get(pad.component_id)
                positional = lc is None or lc.kicad is None or lc.kicad.symbol_lib == "Connector_Generic"
                pins = _pins_for(s, pad.pin_role, lc, positional)
            if not pins:
                sheet.notes.append(f"{pad.ref}: no symbol pin for {pad.pin_role!r} on net {net.name}")
            for p in pins:
                pin_nets.setdefault((s.ref, p.number), net.name)

    blocks: list[Block] = []
    if BOARD_KEY in symbols:
        blocks.append(_stacked_block("board", [symbols[BOARD_KEY]], pin_nets))
    singles = [symbols[p.key] for p in parts if p.part_id is None]
    chunk: list[Symbol] = []
    height = 0.0
    for s in singles:
        x0, y0, x1, y1 = s.extent()
        if chunk and height + (y1 - y0) > _MAX_STACK:
            blocks.append(_stacked_block(f"peripherals{len(blocks)}", chunk, pin_nets))
            chunk, height = [], 0.0
        chunk.append(s)
        height += (y1 - y0) + _ROW_GAP
    if chunk:
        blocks.append(_stacked_block(f"peripherals{len(blocks)}", chunk, pin_nets))

    sub_parts: dict[str, list] = {}
    for p in parts:
        if p.part_id is not None:
            sub_parts.setdefault(p.component_id, []).append(p)
    for comp_id, plist in sub_parts.items():
        lib_comp = lib_comps.get(comp_id)
        sub = lib_comp.subcircuit if lib_comp is not None else None
        by_part = {p.part_id: symbols[p.key] for p in plist}
        if sub is None or sub.schematic is None:
            blocks.append(_stacked_block(comp_id, list(by_part.values()), pin_nets))
            continue
        node_nets: dict[str, str] = {}
        part_pin_nodes: dict[str, dict[str, str]] = {}
        for sp in sub.parts:
            part_pin_nodes[sp.id] = dict(sp.pins)
            s = by_part[sp.id]
            for pin_name, node in sp.pins.items():
                for pin in _pins_for(s, pin_name, None, False):
                    if (s.ref, pin.number) in pin_nets:
                        node_nets.setdefault(node, pin_nets[(s.ref, pin.number)])
        inside = {s.ref for s in by_part.values()}
        outside = {net for (ref, _), net in pin_nets.items() if ref not in inside}
        shared = {node for node, net in node_nets.items() if net in outside}
        internal = {node for node, net in node_nets.items() if net == local_net_name(comp_id, node)}
        blocks.append(_laid_out_block(comp_id, sub.schematic, by_part, node_nets, part_pin_nodes, internal, shared, sheet.notes))
        leftovers = [by_part[pid] for pid in by_part if pid not in sub.schematic.parts]
        if leftovers:
            sheet.notes.append(f"{comp_id}: {len(leftovers)} part(s) have no place in the layout; stacked beside it")
            blocks.append(_stacked_block(f"{comp_id}.rest", leftovers, pin_nets))

    # Pack: columns left to right, each filled top to bottom.
    x, y, col_w = _LEFT, _TOP, 0.0
    for b in blocks:
        if y > _TOP and y + b.h > _BOTTOM:
            x, y, col_w = x + col_w + _COL_GAP, _TOP, 0.0
        _emit_block(sheet, syms, b, snap(x + b.pad_left), snap(y + b.pad_top), pin_nets)
        y += b.h + 2 * _ROW_GAP
        col_w = max(col_w, b.w)

    # One PWR_FLAG per rail nothing on the sheet drives (a board whose
    # rail pins are power outputs drives its own), in a row bottom left.
    driven = set()
    for s in sheet.symbols:
        for p in s.pins:
            if p.etype == "power_out" and (s.ref, p.number) in pin_nets:
                driven.add(pin_nets[(s.ref, p.number)])
    rails = sorted({n for n in pin_nets.values() if n in _POWER_SYMBOLS} - driven)
    fx, fy = snap(_LEFT + 4 * GRID), snap(_BOTTOM + 14 * GRID)
    for net in rails:
        sheet.power(syms, net, fx, fy, 0)
        sheet.wire((fx, fy), (_r(fx + 6 * GRID), fy))
        sheet.flag(syms, _r(fx + 6 * GRID), fy)
        fx = snap(fx + 20 * GRID)

    _add_junctions(sheet)
    sheet.embedded = syms.embedded
    return sheet


def _emit_block(sheet: Sheet, syms: _Symbols, b: Block, ox: float, oy: float, pin_nets: dict) -> None:
    for s in b.symbols:
        s.x, s.y = snap(s.x + ox), snap(s.y + oy)
        sheet.symbols.append(s)
    for pl in b.wires:
        sheet.polyline([(snap(x + ox), snap(y + oy)) for x, y in pl])
    for net, x, y, kind, rot in b.ports:
        px, py = snap(x + ox), snap(y + oy)
        if kind == "power" and sheet.power(syms, net, px, py, rot):
            continue
        sheet.label(net, px, py, rot)
    if b.loose is None:
        for s in b.symbols:
            for p in s.pins:
                net = pin_nets.get((s.ref, p.number))
                x, y = s.pin_at(p)
                if net is None:
                    _no_connect(sheet, s, p)
                else:
                    dx, dy = s.pin_out(p)
                    sheet.terminate(syms, net, x, y, dx, dy)
        return
    for s, p, net in b.loose:
        x, y = s.pin_at(p)
        dx, dy = s.pin_out(p)
        sheet.terminate(syms, net, x, y, dx, dy)
    for s in b.symbols:
        for p in s.pins:
            if (s.ref, p.number) not in pin_nets:
                _no_connect(sheet, s, p)


def _no_connect(sheet: Sheet, s: Symbol, p: SymbolPin) -> None:
    """A pin the library already types as unconnected needs no flag, and
    ERC objects to one."""
    if p.etype in ("no_connect", "unconnected"):
        return
    pt = s.pin_at(p)
    if pt not in sheet.no_connects:
        sheet.no_connects.append(pt)


def _add_junctions(sheet: Sheet) -> None:
    """A junction wherever three things meet, or a wire or pin ends on the
    inside of another wire: that is what makes a T connect in KiCad."""
    ends: dict[Point, int] = {}
    for a, b in sheet.wires:
        ends[a] = ends.get(a, 0) + 1
        ends[b] = ends.get(b, 0) + 1
    # Stacked pins of one symbol (a module's GNDs) are one connection.
    pins: dict[Point, int] = {}
    for s in sheet.symbols:
        for pt in {s.pin_at(p) for p in s.pins}:
            pins[pt] = pins.get(pt, 0) + 1
    for pt in sorted(set(ends) | set(pins)):
        n = ends.get(pt, 0) + pins.get(pt, 0)
        if any(_on_segment(pt, a, b) for a, b in sheet.wires):
            n += 2
        if n >= 3:
            sheet.junctions.append(pt)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _at(x: float, y: float, rot: Optional[int] = 0) -> list:
    out: list = ["at", _r(x), _r(y)]
    if rot is not None:
        out.append(rot)
    return out


def _font(hide: bool = False, justify: Optional[str] = None) -> list:
    eff: list = ["effects", ["font", ["size", 1.27, 1.27]]]
    if justify:
        eff.append(["justify", justify])
    if hide:
        eff.append(["hide", "yes"])
    return eff


def _prop(name: str, value: str, x: float, y: float, *, rot: int = 0, hide: bool = False) -> list:
    return ["property", QStr(name), QStr(value), _at(x, y, rot), _font(hide=hide, justify=None if hide else "left")]


def _text_at(s: Symbol, name: str) -> tuple[float, float, int]:
    """Where the library puts this field, carried with the symbol; text
    stays horizontal or vertical, never upside down."""
    x, y, angle = s.props.get(name, (0.0, 0.0, 0))
    ox, oy = _xform(x, y, s.rot, s.mirror)
    return (s.x + ox, s.y + oy, (angle + s.rot) % 180)


def _symbol_el(sheet: Sheet, s: Symbol, root: str) -> list:
    rx, ry, rrot = _text_at(s, "Reference")
    vx, vy, vrot = _text_at(s, "Value")
    el: list = ["symbol", ["lib_id", QStr(s.lib_id)], _at(s.x, s.y, s.rot)]
    if s.mirror:
        el.append(["mirror", s.mirror])
    el += [
        ["unit", 1],
        ["exclude_from_sim", "yes" if s.power else "no"],
        ["in_bom", "no" if s.power else "yes"],
        ["on_board", "yes"],
        ["dnp", "no"],
        ["uuid", QStr(sheet.uid(f"sym:{s.ref}"))],
        _prop("Reference", s.ref, rx, ry, rot=rrot, hide=s.power),
        _prop("Value", s.value, vx, vy, rot=vrot),
        _prop("Footprint", s.footprint, s.x, s.y, hide=True),
        _prop("Datasheet", "~", s.x, s.y, hide=True),
    ]
    for p in s.pins:
        el.append(["pin", QStr(p.number), ["uuid", QStr(sheet.uid(f"pin:{s.ref}:{p.number}"))]])
    el.append(["instances", ["project", QStr(sheet.design_id),
                             ["path", QStr(f"/{root}"), ["reference", QStr(s.ref)], ["unit", 1]]]])
    return el


def render_sheet(sheet: Sheet) -> str:
    root = sheet.uid("sheet")
    doc: list = [
        "kicad_sch",
        ["version", 20231120],
        ["generator", QStr("wirestudio")],
        ["generator_version", QStr("8.0")],
        ["uuid", QStr(root)],
        ["paper", QStr(_PAGE)],
        ["title_block", ["title", QStr(sheet.title)], ["comment", 1, QStr("Generated by wirestudio")]],
        ["lib_symbols", *[sheet.embedded[k] for k in sorted(sheet.embedded)]],
    ]
    for (a, b) in sheet.wires:
        doc.append(["wire", ["pts", ["xy", a[0], a[1]], ["xy", b[0], b[1]]],
                    ["stroke", ["width", 0], ["type", "default"]],
                    ["uuid", QStr(sheet.uid(f"wire:{a}:{b}"))]])
    for (x, y) in sheet.junctions:
        doc.append(["junction", _at(x, y, None), ["diameter", 0], ["color", 0, 0, 0, 0],
                    ["uuid", QStr(sheet.uid(f"junction:{x}:{y}"))]])
    for (x, y) in sheet.no_connects:
        doc.append(["no_connect", _at(x, y, None), ["uuid", QStr(sheet.uid(f"nc:{x}:{y}"))]])
    for i, (name, x, y, rot) in enumerate(sheet.labels):
        justify = "right" if rot in (180, 270) else "left"
        doc.append(["global_label", QStr(name), ["shape", "bidirectional"], _at(x, y, rot),
                    ["fields_autoplaced", "yes"], _font(justify=justify),
                    ["uuid", QStr(sheet.uid(f"label:{i}:{name}"))],
                    ["property", QStr("Intersheetrefs"), QStr("${INTERSHEET_REFS}"), _at(x, y, 0),
                     _font(hide=True)]])
    for s in sheet.symbols:
        doc.append(_symbol_el(sheet, s, root))
    doc.append(["sheet_instances", ["path", QStr("/"), ["page", QStr("1")]]])
    return dump_sexpr(doc) + "\n"


def generate_kicad_sch(design: Design, library: Library, *, symbol_dir: Optional[Path] = None) -> str:
    """The design as a KiCad 8 schematic file."""
    return render_sheet(build_sheet(design, library, symbol_dir=symbol_dir))


def expected_connectivity(sheet: Sheet) -> set[frozenset[tuple[str, str]]]:
    """The pin groups the sheet is meant to connect, for check_sch to hold
    against the netlist KiCad reads back from the geometry."""
    groups: dict[str, set[tuple[str, str]]] = {}
    for (ref, number), net in sheet.pin_nets.items():
        groups.setdefault(net, set()).add((ref, number))
    return {frozenset(g) for g in groups.values() if len(g) > 1}


__all__ = [
    "GRID", "SchematicUnavailable", "Sheet", "build_sheet", "expected_connectivity",
    "generate_kicad_sch", "render_sheet", "sch_status", "snap",
]
