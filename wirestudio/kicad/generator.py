"""KiCad schematic export (0.9).

Walks a `design.json` and emits a SKiDL Python script that, when run,
produces a `.kicad_sch` the user opens in KiCad. The studio doesn't
import or run SKiDL itself -- a hard runtime dep would pull in numpy
+ a chunk of EDA-toolchain weight that's wrong for a server. Instead
the user runs the generated script locally:

    pip install skidl
    python <design_id>.skidl.py
    # produces <design_id>.kicad_sch in the cwd

Mapping: each `library/components/<id>.yaml` and
`library/boards/<id>.yaml` carries a `kicad:` block (KicadSymbolRef)
that names the symbol library + symbol + optional footprint + pin
remap. Unmapped components fall back to a generic 0.1" header with a
TODO comment so the script always runs; the user can edit the .py
before re-running, or fill in the `kicad:` block in the library YAML
and re-export.

Pure: no I/O, no SKiDL import. Tests verify the emitted text is
syntactically plausible (executes under `compile()`) and that key
mappings (symbol, footprint, pin_map applied) appear verbatim.
"""
from __future__ import annotations

import re

from wirestudio.library import KicadSymbolRef, Library
from wirestudio.model import Design


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PY_IDENT_RE = re.compile(r"[^A-Za-z0-9_]")


def _py_var(name: str) -> str:
    """Coerce an arbitrary id into a safe Python identifier prefixed
    with `c_` (component) or `n_` (net) by the caller."""
    out = _PY_IDENT_RE.sub("_", name)
    if out and out[0].isdigit():
        out = "_" + out
    return out


def _quote(s: str) -> str:
    """JSON-style double-quoted string literal that Python accepts."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---------------------------------------------------------------------------
# Per-component / per-board emission
# ---------------------------------------------------------------------------

def _emit_part(var: str, ref: str, kicad: KicadSymbolRef, comment: str | None = None) -> str:
    parts = [
        _quote(kicad.symbol_lib),
        _quote(kicad.symbol),
        f"ref={_quote(ref)}",
    ]
    if kicad.value:
        parts.append(f"value={_quote(kicad.value)}")
    if kicad.footprint:
        parts.append(f"footprint={_quote(kicad.footprint)}")
    line = f"{var} = Part({', '.join(parts)})"
    if comment:
        return f"# {comment}\n{line}"
    return line


def _emit_placeholder(var: str, ref: str, lib_id: str) -> str:
    """Fallback when a component has no `kicad:` block. Emits a generic
    4-pin header with a TODO so the script still runs and the user can
    fix it up post-hoc."""
    return (
        f"# TODO: {lib_id} not yet mapped to a KiCad symbol.\n"
        f"# Add a `kicad:` block to library/components/{lib_id}.yaml,\n"
        f"# or replace this Part(...) call with the right symbol manually.\n"
        f"{var} = Part(\"Connector_Generic\", \"Conn_01x04\", "
        f"ref={_quote(ref)}, value={_quote(lib_id)})"
    )


def _resolve_pin_role(role: str, kicad: KicadSymbolRef | None) -> str:
    if kicad and role in kicad.pin_map:
        return kicad.pin_map[role]
    return role


# ---------------------------------------------------------------------------
# Reference-designator allocator
# ---------------------------------------------------------------------------

def _ref_for(category: str, counter: dict[str, int]) -> str:
    prefix = {
        "sensor": "U",
        "binary_sensor": "U",
        "io_expander": "U",
        "display": "U",
        "audio": "U",
        "led": "D",
        "amp": "U",
    }.get(category, "U")
    counter[prefix] = counter.get(prefix, 0) + 1
    return f"{prefix}{counter[prefix]}"


# ---------------------------------------------------------------------------
# Net derivation
# ---------------------------------------------------------------------------

def _net_label_for_target(t: dict, design: Design, used_buses: dict[str, str]) -> str:
    """Map a connection target to a SKiDL net handle.

    rails -> +5V / +3V3 / GND (canonicalised),
    bus -> the bus's id (sda/scl/clk/etc. resolved per role at the call site),
    expander_pin -> a hub-relative net like `mcp_hub_GP3`,
    component -> the parent component's ref-relative HUB net,
    gpio -> a per-pin net like `GPIO13` or `D5`.
    """
    kind = t.get("kind")
    if kind == "rail":
        rail = t.get("rail", "")
        if rail.lower() in ("gnd", "ground"):
            return "GND"
        return f"+{rail}".replace("V3", "V3").replace(" ", "")
    if kind == "gpio":
        pin = t.get("pin") or "UNBOUND"
        return f"NET_{pin}"
    if kind == "bus":
        bus_id = t.get("bus_id") or "UNBOUND"
        return f"BUS_{bus_id}"
    if kind == "expander_pin":
        ex = t.get("expander_id") or "EX"
        n = t.get("number")
        return f"{ex}_GP{n}"
    if kind == "component":
        cid = t.get("component_id") or "PARENT"
        return f"{cid}_REF"
    return "UNCONNECTED"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_PREAMBLE = '''\
"""SKiDL schematic for design '{design_id}' generated by wirestudio.

To produce a .kicad_sch (KiCad 6+), install SKiDL and run this file:

    pip install skidl
    python {design_id}.skidl.py

The script writes <design_id>.kicad_sch + .net + .xml into the current
directory. Edit pin assignments + component overrides above the
generate_*() calls if you want to tweak before re-running.
"""
from skidl import Part, Net, generate_netlist, generate_schematic, TEMPLATE


def build():
    # ---- Power rails -----------------------------------------------------
    GND = Net("GND")
{rail_decls}

    # ---- Component instances --------------------------------------------
{component_decls}

    # ---- Buses ----------------------------------------------------------
{bus_decls}

    # ---- Connections ----------------------------------------------------
{connection_lines}


if __name__ == "__main__":
    build()
    # Default: emit a netlist (.net) + a schematic (.kicad_sch).
    # Comment out either if you only want one.
    generate_netlist()
    generate_schematic()
'''


def generate_skidl(design: Design, library: Library) -> str:
    """Emit a SKiDL Python script. Pure: returns the text."""
    rail_decls = _render_rails(design)
    component_decls, ref_index = _render_components(design, library)
    bus_decls = _render_buses(design)
    connection_lines = _render_connections(design, library, ref_index)
    return _PREAMBLE.format(
        design_id=design.id,
        rail_decls=_indent(rail_decls or "pass", 4),
        component_decls=_indent(component_decls or "pass", 4),
        bus_decls=_indent(bus_decls or "pass", 4),
        connection_lines=_indent(connection_lines or "pass", 4),
    )


def _indent(s: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + line if line.strip() else line for line in s.splitlines())


def _render_rails(design: Design) -> str:
    rails: set[str] = set()
    for c in design.connections:
        t = c.target
        if t.kind == "rail" and t.rail.lower() not in ("gnd", "ground"):
            rails.add(t.rail)
    if not rails:
        return ""
    out: list[str] = []
    for r in sorted(rails):
        out.append(f'NET_PLUS_{_py_var(r)} = Net("+{r}")')
    return "\n".join(out)


def _render_components(
    design: Design, library: Library,
) -> tuple[str, dict[str, str]]:
    """Render Part(...) calls for design + board, return the script
    text plus a {component_id: skidl_var_name} index for connection
    rendering. Also adds the board itself as a Part (the dev module
    sits at the top of the schematic just like a real design)."""
    counter: dict[str, int] = {}
    lines: list[str] = []
    ref_index: dict[str, str] = {}

    # Board first.
    try:
        board = library.board(design.board.library_id)
    except FileNotFoundError:
        board = None
    if board is not None:
        var = "board"
        ref = "M1"
        if board.kicad is not None:
            lines.append(_emit_part(var, ref, board.kicad,
                                     comment=f"Board: {board.name}"))
        else:
            lines.append(_emit_placeholder(var, ref, board.id))
        ref_index["__board__"] = var

    # Components.
    for c in design.components:
        var = f"c_{_py_var(c.id)}"
        try:
            lib_comp = library.component(c.library_id)
        except FileNotFoundError:
            lib_comp = None
        if lib_comp is None or lib_comp.kicad is None:
            ref = _ref_for("sensor", counter)
            lines.append(_emit_placeholder(var, ref, c.library_id))
        else:
            ref = _ref_for(lib_comp.category, counter)
            lines.append(_emit_part(var, ref, lib_comp.kicad,
                                     comment=f"{c.id} ({lib_comp.name})"))
        ref_index[c.id] = var

    return "\n".join(lines), ref_index


def _render_buses(design: Design) -> str:
    if not design.buses:
        return ""
    out: list[str] = []
    for b in design.buses:
        out.append(f'NET_BUS_{_py_var(b.id)} = Net("BUS_{b.id}")  # {b.type} bus')
    return "\n".join(out)


def _render_connections(
    design: Design, library: Library, ref_index: dict[str, str],
) -> str:
    """Render `<comp>[<pin>] += <net>` lines. SKiDL accepts pin names
    in __getitem__; we use the role (or remapped role via pin_map)
    here, so the script lines up with the component's KiCad symbol."""
    lines: list[str] = []
    by_id = {c.id: c for c in design.components}
    for conn in design.connections:
        comp_var = ref_index.get(conn.component_id)
        if comp_var is None:
            lines.append(f'# skipped: {conn.component_id}.{conn.pin_role} (component not in design)')
            continue
        comp = by_id.get(conn.component_id)
        kicad = None
        if comp is not None:
            try:
                lib_comp = library.component(comp.library_id)
                kicad = lib_comp.kicad
            except FileNotFoundError:
                pass
        pin_name = _resolve_pin_role(conn.pin_role, kicad)
        net_expr = _net_handle_for(conn.target, design, ref_index)
        lines.append(f'{comp_var}[{_quote(pin_name)}] += {net_expr}')
    return "\n".join(lines)


def _net_handle_for(target, design: Design, ref_index: dict[str, str]) -> str:
    """Return a SKiDL expression that evaluates to the net for `target`.
    For rails we reference the per-script Net handle (NET_PLUS_*, GND);
    for buses we reference NET_BUS_<id>; for gpio/expander_pin we build
    an inline Net(...) so each unique landing gets a fresh handle.
    For component (hub) targets we use the hub's ref var."""
    kind = target.kind
    if kind == "rail":
        if target.rail.lower() in ("gnd", "ground"):
            return "GND"
        return f"NET_PLUS_{_py_var(target.rail)}"
    if kind == "bus":
        return f"NET_BUS_{_py_var(target.bus_id)}"
    if kind == "gpio":
        pin = target.pin or "UNBOUND"
        return f'Net("GPIO_{_py_var(pin)}")'
    if kind == "expander_pin":
        ex = target.expander_id or "EX"
        n = target.number
        return f'Net("{ex}_GP{n}")'
    if kind == "component":
        cid = target.component_id or "PARENT"
        return f'Net("{cid}_HUB")'
    return 'Net("UNCONNECTED")'


# Re-export helpers used by tests.
__all__ = ["generate_skidl", "_py_var"]
