"""Minimal `.kicad_sym` reader for the library importer.

KiCad symbol libraries are s-expressions. We don't take a dependency on
`kiutils` here -- this reads exactly the three things the importer needs
(symbol names, per-pin name + number, the Footprint property) and nothing
else. Same stance as the rest of wirestudio's upstream consumption:
schema-derived data, no vendored EDA-toolchain weight.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_LP = object()  # "(" sentinel -- never collides with a quoted string value
_RP = object()  # ")" sentinel


@dataclass
class KicadSymbol:
    """One symbol from a `.kicad_sym` library, flattened to what the
    importer cares about. `pins` is a list of (name, number) in file
    order; `extends` names a base symbol when the entry is derived."""
    name: str
    properties: dict[str, str] = field(default_factory=dict)
    pins: list[tuple[str, str]] = field(default_factory=list)
    extends: str | None = None


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
            tokens.append("".join(buf))
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


def _parse_pin(el: list) -> tuple[str, str] | None:
    name = number = None
    for child in el[1:]:
        if isinstance(child, list) and child:
            if child[0] == "name" and len(child) >= 2:
                name = child[1]
            elif child[0] == "number" and len(child) >= 2:
                number = child[1]
    if name is None and number is None:
        return None
    return (name or "", number or "")


def _parse_symbol(el: list) -> KicadSymbol:
    sym = KicadSymbol(name=el[1] if len(el) > 1 else "")
    for child in el[2:]:
        if not isinstance(child, list) or not child:
            continue
        head = child[0]
        if head == "property" and len(child) >= 3:
            sym.properties[child[1]] = child[2]
        elif head == "extends" and len(child) >= 2:
            sym.extends = child[1]
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
