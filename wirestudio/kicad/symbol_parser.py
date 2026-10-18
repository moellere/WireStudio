"""Minimal `.kicad_sym` reader and s-expression writer.

KiCad symbol libraries are s-expressions. We don't take a dependency on
`kiutils` here -- this reads what the importer needs (symbol names,
per-pin name + number, the Footprint property) plus what the schematic
writer needs (pin geometry, body extents, and the symbol's own text to
embed in a sheet), and nothing else. Same stance as the rest of
wirestudio's upstream consumption: schema-derived data, no vendored
EDA-toolchain weight.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from pathlib import Path

_LP = object()  # "(" sentinel -- never collides with a quoted string value
_RP = object()  # ")" sentinel


class QStr(str):
    """A token that was quoted in the source, so `dump_sexpr` quotes it
    again. Compares equal to the plain string."""


@dataclass
class KicadSymbol:
    """One symbol from a `.kicad_sym` library, flattened to what the
    importer cares about. `pins` is a list of (name, number) in file
    order; `extends` names a base symbol when the entry is derived."""
    name: str
    properties: dict[str, str] = field(default_factory=dict)
    pins: list[tuple[str, str]] = field(default_factory=list)
    extends: str | None = None


@dataclass(frozen=True)
class SymbolPin:
    """A pin's geometry in symbol space (mm, Y up): `x, y` is the
    connection point and `angle` the direction the pin runs toward the
    body from there (0 right, 90 up, 180 left, 270 down)."""
    name: str
    number: str
    x: float
    y: float
    angle: int
    length: float
    etype: str


def _tokenize(text: str) -> list:
    tokens: list = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "(":
            tokens.append(_LP)
            i += 1
        elif ch == ")":
            tokens.append(_RP)
            i += 1
        elif ch.isspace():
            i += 1
        elif ch == '"':
            i += 1
            buf: list[str] = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            i += 1  # closing quote
            tokens.append(QStr("".join(buf)))
        else:
            buf = []
            while i < n and not text[i].isspace() and text[i] not in '()"':
                buf.append(text[i])
                i += 1
            tokens.append("".join(buf))
    return tokens


def parse_sexpr(text: str) -> list:
    """Parse one s-expression into nested lists of strings."""
    tokens = _tokenize(text)
    pos = 0

    def parse():
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError("unexpected end of s-expression")
        tok = tokens[pos]
        if tok is _LP:
            pos += 1
            lst: list = []
            while pos < len(tokens) and tokens[pos] is not _RP:
                lst.append(parse())
            if pos >= len(tokens):
                raise ValueError("unbalanced parentheses")
            pos += 1  # consume ")"
            return lst
        if tok is _RP:
            raise ValueError("unexpected ')'")
        pos += 1
        return tok

    return parse()


def _atom(value) -> str:
    if isinstance(value, QStr):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return fmt_num(value)
    return str(value)


def fmt_num(v: float) -> str:
    """A number the way KiCad writes it: no exponent, no trailing zeros,
    no negative zero."""
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def dump_sexpr(node, indent: int = 0) -> str:
    """Write a tree back out. Order is preserved exactly (KiCad's grammar
    has atoms after lists in places); lists go on their own lines."""
    pad = "  " * indent
    if not isinstance(node, list):
        return pad + _atom(node)
    out = pad + "("
    first = True
    for item in node:
        if isinstance(item, list):
            out += "\n" + dump_sexpr(item, indent + 1)
        else:
            out += ("" if first else " ") + _atom(item)
        first = False
    return out + ")"


def _num(tok) -> float:
    return float(tok)


def _children(el: list, head: str) -> list[list]:
    return [c for c in el[1:] if isinstance(c, list) and c and c[0] == head]


def _child(el: list, head: str) -> list | None:
    found = _children(el, head)
    return found[0] if found else None


def _pin_geometry(el: list) -> SymbolPin | None:
    at = _child(el, "at")
    name, number = _child(el, "name"), _child(el, "number")
    if at is None or len(at) < 3:
        return None
    length = _child(el, "length")
    return SymbolPin(
        name=str(name[1]) if name and len(name) > 1 else "",
        number=str(number[1]) if number and len(number) > 1 else "",
        x=_num(at[1]), y=_num(at[2]),
        angle=int(float(at[3])) % 360 if len(at) > 3 else 0,
        length=_num(length[1]) if length and len(length) > 1 else 0.0,
        etype=str(el[1]) if len(el) > 1 and not isinstance(el[1], list) else "passive",
    )


def symbol_pins(el: list) -> list[SymbolPin]:
    """Every pin of a symbol element with its geometry, units hoisted."""
    out: list[SymbolPin] = []
    for child in el[2:]:
        if not isinstance(child, list) or not child:
            continue
        if child[0] == "pin":
            pin = _pin_geometry(child)
            if pin is not None:
                out.append(pin)
        elif child[0] == "symbol":
            out.extend(symbol_pins(child))
    return out


def symbol_bbox(el: list) -> tuple[float, float, float, float]:
    """(xmin, ymin, xmax, ymax) of the symbol's drawn body and pins in
    symbol space (mm, Y up). Text is not counted."""
    xs: list[float] = []
    ys: list[float] = []

    def take(x, y):
        xs.append(_num(x))
        ys.append(_num(y))

    def walk(node: list) -> None:
        for child in node[1:]:
            if not isinstance(child, list) or not child:
                continue
            head = child[0]
            if head in ("rectangle",):
                for key in ("start", "end"):
                    pt = _child(child, key)
                    if pt:
                        take(pt[1], pt[2])
            elif head == "circle":
                c, r = _child(child, "center"), _child(child, "radius")
                if c and r:
                    cx, cy, rr = _num(c[1]), _num(c[2]), _num(r[1])
                    take(cx - rr, cy - rr)
                    take(cx + rr, cy + rr)
            elif head in ("polyline", "arc"):
                pts = _child(child, "pts")
                if pts:
                    for xy in pts[1:]:
                        if isinstance(xy, list) and xy[0] == "xy":
                            take(xy[1], xy[2])
                for key in ("start", "mid", "end"):
                    pt = _child(child, key)
                    if pt:
                        take(pt[1], pt[2])
            elif head == "pin":
                pin = _pin_geometry(child)
                if pin is not None:
                    take(pin.x, pin.y)
                    a = math.radians(pin.angle)
                    take(pin.x + pin.length * math.cos(a), pin.y + pin.length * math.sin(a))
            elif head == "symbol":
                walk(child)

    walk(el)
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def load_symbol_trees(path: str | Path) -> dict[str, list]:
    """Read a `.kicad_sym` file into {symbol_name: element} with the
    quoting preserved, for `embed_symbol`."""
    tree = parse_sexpr(Path(path).read_text())
    if not isinstance(tree, list) or not tree or tree[0] != "kicad_symbol_lib":
        raise ValueError(f"{path} is not a kicad_symbol_lib file")
    return {
        el[1]: el for el in tree[1:]
        if isinstance(el, list) and len(el) > 1 and el[0] == "symbol"
    }


def flatten_symbol(trees: dict[str, list], name: str) -> list:
    """The symbol element with `extends` resolved: the base's body and
    pins under this symbol's name, this symbol's properties and flags
    winning over the base's. A plain symbol comes back as a deep copy."""
    el = trees[name]
    ext = _child(el, "extends")
    if ext is None:
        return copy.deepcopy(el)
    base = flatten_symbol(trees, str(ext[1]))
    base_name = str(base[1])
    out: list = ["symbol", QStr(name)]
    own_props = {str(p[1]): p for p in _children(el, "property")}
    own_heads = {c[0] for c in el[2:] if isinstance(c, list) and c and c[0] not in ("property", "extends", "symbol", "pin")}
    for child in base[2:]:
        if not isinstance(child, list) or not child:
            out.append(child)
            continue
        head = child[0]
        if head == "property" and str(child[1]) in own_props:
            out.append(copy.deepcopy(own_props.pop(str(child[1]))))
        elif head in own_heads:
            continue
        elif head == "symbol" and isinstance(child[1], str) and child[1].startswith(base_name + "_"):
            unit = copy.deepcopy(child)
            unit[1] = QStr(name + child[1][len(base_name):])
            out.append(unit)
        else:
            out.append(copy.deepcopy(child))
    for child in el[2:]:
        if isinstance(child, list) and child and child[0] in own_heads:
            out.append(copy.deepcopy(child))
    out.extend(copy.deepcopy(p) for p in own_props.values())
    return out


def embed_symbol(trees: dict[str, list], name: str, lib: str) -> list:
    """`flatten_symbol` renamed to `Lib:Name` for a sheet's `lib_symbols`
    (nested unit names stay bare, as KiCad writes them)."""
    el = flatten_symbol(trees, name)
    el[1] = QStr(f"{lib}:{name}")
    return el


def _parse_pin(el: list) -> tuple[str, str] | None:
    name = number = None
    for child in el[1:]:
        if isinstance(child, list) and child:
            if child[0] == "name" and len(child) >= 2:
                name = str.__str__(child[1])
            elif child[0] == "number" and len(child) >= 2:
                number = str.__str__(child[1])
    if name is None and number is None:
        return None
    return (name or "", number or "")


def _parse_symbol(el: list) -> KicadSymbol:
    # Plain str, not QStr: the importer dumps these into YAML.
    sym = KicadSymbol(name=str.__str__(el[1]) if len(el) > 1 else "")
    for child in el[2:]:
        if not isinstance(child, list) or not child:
            continue
        head = child[0]
        if head == "property" and len(child) >= 3:
            sym.properties[str.__str__(child[1])] = str.__str__(child[2])
        elif head == "extends" and len(child) >= 2:
            sym.extends = str.__str__(child[1])
        elif head == "pin":
            pin = _parse_pin(child)
            if pin is not None:
                sym.pins.append(pin)
        elif head == "symbol":
            # Nested unit symbol (NAME_x_y). Pins live on the units;
            # hoist them onto the parent.
            sym.pins.extend(_parse_symbol(child).pins)
    return sym


def load_symbols(path: str | Path) -> dict[str, KicadSymbol]:
    """Read a `.kicad_sym` file into {symbol_name: KicadSymbol}."""
    tree = parse_sexpr(Path(path).read_text())
    if not isinstance(tree, list) or not tree or tree[0] != "kicad_symbol_lib":
        raise ValueError(f"{path} is not a kicad_symbol_lib file")
    out: dict[str, KicadSymbol] = {}
    for el in tree[1:]:
        if isinstance(el, list) and el and el[0] == "symbol":
            sym = _parse_symbol(el)
            out[sym.name] = sym
    return out


def resolve_symbol(symbols: dict[str, KicadSymbol], name: str) -> KicadSymbol:
    """Return `name` with `extends` inheritance applied. A derived symbol
    inherits the base's properties (own values win) and its pins when it
    declares none of its own."""
    sym = symbols[name]
    if not sym.extends:
        return sym
    if sym.extends not in symbols:
        raise ValueError(f"symbol {name!r} extends unknown base {sym.extends!r}")
    base = resolve_symbol(symbols, sym.extends)
    return KicadSymbol(
        name=sym.name,
        properties={**base.properties, **sym.properties},
        pins=sym.pins or base.pins,
        extends=None,
    )
