"""`.kicad_pcb` board export (PCB layout, step 2).

Walks a ``design.json`` and emits a KiCad 8 board file: every component +
board footprint embedded and grid-placed, each pad bound to the net it shares
in the design, plus an ``Edge.Cuts`` outline. No routing -- the user opens it
in KiCad's PCB editor with a complete ratsnest and routes (or hands it to an
autorouter, a later step toward 1.0).

Unlike the SKiDL schematic (a pure text emit with no external data), the board
embeds real footprint geometry, so it needs the pinned KiCad **footprint**
libraries (the ``.kicad_mod`` files) and the **symbol** libraries (to map a
component's pin role -> symbol pin name -> pin number -> footprint pad). It is
therefore feature-gated the same way the schematic *render* is gated on
``kicad-cli``: ``pcb_status()`` probes for the libraries and the API/web gate
the export on it.

Determinism: same ``design.json`` + same pinned libraries -> byte-identical
board. Reference designators and net names come from ``wirestudio.kicad.netlist``
so the board and the schematic agree.

Known limitation (step 2): the dev board's own pads aren't bound to nets -- the
library models boards as generic headers with no GPIO-name -> pad map, so the
board footprint is placed but its pins float, exactly as in the schematic. Nets
shared between components (rails, buses, expander/hub pins) get a ratsnest.
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Optional

from wirestudio.kicad.netlist import BOARD_KEY, assign_refs, build_netlist
from wirestudio.kicad.symbol_parser import load_symbols, resolve_symbol
from wirestudio.library import Library
from wirestudio.model import Design

# Grid placement (mm). Parts land on a coarse grid; the user arranges in KiCad.
_PITCH_MM = 25.4
_ORIGIN_MM = 25.4
_MARGIN_MM = 12.7  # Edge.Cuts border around the placement bounding box

_FOOTPRINT_ENV_VARS = (
    "KICAD8_FOOTPRINT_DIR", "KICAD9_FOOTPRINT_DIR", "KICAD7_FOOTPRINT_DIR",
    "KICAD6_FOOTPRINT_DIR", "KICAD_FOOTPRINT_DIR",
)
_SYMBOL_ENV_VARS = (
    "KICAD8_SYMBOL_DIR", "KICAD9_SYMBOL_DIR", "KICAD7_SYMBOL_DIR",
    "KICAD6_SYMBOL_DIR", "KICAD_SYMBOL_DIR",
)

# Canonical KiCad 8 two-layer board layer table.
_LAYERS = """\
	(0 "F.Cu" signal)
	(31 "B.Cu" signal)
	(32 "B.Adhes" user "B.Adhesive")
	(33 "F.Adhes" user "F.Adhesive")
	(34 "B.Paste" user)
	(35 "F.Paste" user)
	(36 "B.SilkS" user "B.Silkscreen")
	(37 "F.SilkS" user "F.Silkscreen")
	(38 "B.Mask" user)
	(39 "F.Mask" user)
	(40 "Dwgs.User" user "User.Drawings")
	(41 "Cmts.User" user "User.Comments")
	(42 "Eco1.User" user "User.Eco1")
	(43 "Eco2.User" user "User.Eco2")
	(44 "Edge.Cuts" user)
	(45 "Margin" user)
	(46 "B.CrtYd" user "B.Courtyard")
	(47 "F.CrtYd" user "F.Courtyard")
	(48 "B.Fab" user)
	(49 "F.Fab" user)"""


class PcbUnavailable(RuntimeError):
    """The pinned KiCad footprint/symbol libraries aren't available."""


def _dir_from_env(env_vars: tuple[str, ...]) -> Optional[Path]:
    for var in env_vars:
        val = os.environ.get(var)
        if val and Path(val).is_dir():
            return Path(val)
    return None


def _resolve_footprint_dir() -> Optional[Path]:
    return _dir_from_env(_FOOTPRINT_ENV_VARS)


def _resolve_symbol_dir() -> Optional[Path]:
    return _dir_from_env(_SYMBOL_ENV_VARS)


def pcb_status() -> dict:
    """Probe for the libraries the board export needs. Shape mirrors the
    schematic render status: ``available`` is the headline, the rest says
    what's missing."""
    fp, sym = _resolve_footprint_dir(), _resolve_symbol_dir()
    available = fp is not None and sym is not None
    reason = None
    if not available:
        missing = []
        if fp is None:
            missing.append("footprint libraries not found (set KICAD8_FOOTPRINT_DIR)")
        if sym is None:
            missing.append("symbol libraries not found (set KICAD8_SYMBOL_DIR)")
        reason = "; ".join(missing)
    return {
        "available": available,
        "footprints": fp is not None,
        "symbols": sym is not None,
        "reason": reason,
    }


def _mod_path(footprint_ref: str, fp_dir: Path) -> Path:
    """`LIB:NAME` -> `<fp_dir>/LIB.pretty/NAME.kicad_mod`."""
    lib, name = footprint_ref.split(":", 1)
    return fp_dir / f"{lib}.pretty" / f"{name}.kicad_mod"


def _resolve_pad_number(
    role: str, lib_comp, sym_dir: Path, sym_cache: dict,
) -> Optional[str]:
    """Map a component pin role to its KiCad footprint pad number.

    Generic ``Connector_Generic`` symbols have positional pins, so the role
    binds to its 1-based index in the component's electrical pin list. Real
    symbols go role ->(pin_map) symbol pin name ->(symbol) pin number, which
    equals the footprint pad number. Returns None when it can't resolve (the
    caller collects these as warnings)."""
    kicad = lib_comp.kicad
    if kicad is None:
        return None
    if kicad.symbol_lib == "Connector_Generic":
        roles = [p.role for p in lib_comp.electrical.pins]
        return str(roles.index(role) + 1) if role in roles else None
    pin_name = kicad.pin_map.get(role, role)
    syms = sym_cache.get(kicad.symbol_lib)
    if syms is None:
        path = sym_dir / f"{kicad.symbol_lib}.kicad_sym"
        syms = load_symbols(path) if path.is_file() else {}
        sym_cache[kicad.symbol_lib] = syms
    if kicad.symbol not in syms:
        return None
    for name, number in resolve_symbol(syms, kicad.symbol).pins:
        if name == pin_name:
            return number
    return None


def _inject_pad_net(text: str, pad_num: str, net_idx: int, net_name: str) -> str:
    """Add ``(net idx "name")`` to the first ``(pad "pad_num" ...)`` block by
    scanning to its matching close paren (skipping quoted strings)."""
    marker = f'(pad "{pad_num}" '
    start = text.find(marker)
    if start == -1:
        return text
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    return f'{text[:i]}\t\t(net {net_idx} "{net_name}")\n\t{text[i:]}'


def _embed_footprint(
    mod_text: str, footprint_ref: str, ref: str, value: str,
    x: float, y: float, pad_nets: dict[str, tuple[int, str]],
) -> str:
    """Turn a standalone ``.kicad_mod`` into a placed board footprint: rewrite
    the name to ``LIB:NAME``, inject placement, set the reference + value, and
    bind pad nets. Pad/graphic geometry is preserved verbatim."""
    lib, name = footprint_ref.split(":", 1)
    opener = f'(footprint "{name}"'
    text = mod_text.replace(
        opener, f'(footprint "{footprint_ref}"\n\t(at {_fmt(x)} {_fmt(y)})', 1,
    )
    text = text.replace(
        '(property "Reference" "REF**"', f'(property "Reference" "{ref}"', 1,
    )
    text = re.sub(
        r'\(property "Value" "[^"]*"', f'(property "Value" "{value}"', text, count=1,
    )
    for pad_num, (net_idx, net_name) in pad_nets.items():
        text = _inject_pad_net(text, pad_num, net_idx, net_name)
    return _indent(text, 1)


def _fmt(v: float) -> str:
    """Trim trailing zeros so 25.4 -> '25.4', 50.0 -> '50'."""
    return f"{v:.4f}".rstrip("0").rstrip(".")


def _indent(block: str, level: int) -> str:
    pad = "\t" * level
    return "\n".join(pad + line if line else line for line in block.splitlines())


def generate_kicad_pcb(
    design: Design, library: Library, *,
    footprint_dir: Optional[Path] = None, symbol_dir: Optional[Path] = None,
) -> str:
    """Emit a KiCad 8 ``.kicad_pcb`` for ``design``. Pure given the inputs.

    Raises ``PcbUnavailable`` when the libraries aren't found and ``ValueError``
    when a referenced footprint doesn't resolve to a ``.kicad_mod`` (the
    footprint gate keeps this from happening for bundled examples)."""
    fp_dir = Path(footprint_dir) if footprint_dir else _resolve_footprint_dir()
    sym_dir = Path(symbol_dir) if symbol_dir else _resolve_symbol_dir()
    if fp_dir is None or sym_dir is None:
        raise PcbUnavailable(pcb_status()["reason"])

    refs = assign_refs(design, library)
    nets = build_netlist(design, library)
    net_index = {net.name: i + 1 for i, net in enumerate(nets)}

    # Resolve each net pad to a footprint pad number, grouped per ref.
    components_by_id = {c.id: c for c in design.components}
    pad_nets_by_ref: dict[str, dict[str, tuple[int, str]]] = {}
    sym_cache: dict[str, dict] = {}
    for net in nets:
        for pad in net.pads:
            comp = components_by_id.get(pad.component_id)
            if comp is None:
                continue
            lib_comp = library.component(comp.library_id)
            num = _resolve_pad_number(pad.pin_role, lib_comp, sym_dir, sym_cache)
            if num is not None:
                pad_nets_by_ref.setdefault(pad.ref, {})[num] = (
                    net_index[net.name], net.name,
                )

    # The placement order: board (M1) first, then components in design order.
    placements: list[tuple[str, str, str]] = []  # (ref, footprint_ref, value)
    try:
        board = library.board(design.board.library_id)
    except FileNotFoundError:
        board = None
    if board is not None and board.kicad is not None and board.kicad.footprint:
        placements.append((
            refs[BOARD_KEY], board.kicad.footprint, board.kicad.value or board.id,
        ))
    for c in design.components:
        lib_comp = library.component(c.library_id)
        if lib_comp.kicad is not None and lib_comp.kicad.footprint:
            placements.append((
                refs[c.id], lib_comp.kicad.footprint,
                lib_comp.kicad.value or c.library_id,
            ))

    cols = max(1, math.ceil(math.sqrt(len(placements))))
    fp_blocks: list[str] = []
    unresolved: list[str] = []
    max_x = max_y = 0.0
    for i, (ref, footprint_ref, value) in enumerate(placements):
        mod = _mod_path(footprint_ref, fp_dir)
        if not mod.is_file():
            unresolved.append(f"{ref}: {footprint_ref}")
            continue
        x = _ORIGIN_MM + (i % cols) * _PITCH_MM
        y = _ORIGIN_MM + (i // cols) * _PITCH_MM
        max_x, max_y = max(max_x, x), max(max_y, y)
        fp_blocks.append(_embed_footprint(
            mod.read_text(), footprint_ref, ref, value, x, y,
            pad_nets_by_ref.get(ref, {}),
        ))

    if unresolved:
        raise ValueError(
            "footprints not found in the library: " + "; ".join(unresolved)
        )

    net_decls = '\t(net 0 "")\n' + "\n".join(
        f'\t(net {net_index[net.name]} "{net.name}")' for net in nets
    )
    x0, y0 = _ORIGIN_MM - _MARGIN_MM, _ORIGIN_MM - _MARGIN_MM
    x1, y1 = max_x + _MARGIN_MM, max_y + _MARGIN_MM
    outline = (
        "\t(gr_rect\n"
        f"\t\t(start {_fmt(x0)} {_fmt(y0)})\n"
        f"\t\t(end {_fmt(x1)} {_fmt(y1)})\n"
        "\t\t(stroke (width 0.1) (type default))\n"
        "\t\t(fill none)\n"
        '\t\t(layer "Edge.Cuts")\n'
        "\t)"
    )
    return (
        '(kicad_pcb\n'
        "\t(version 20240108)\n"
        '\t(generator "wirestudio")\n'
        '\t(generator_version "8.0")\n'
        "\t(general\n\t\t(thickness 1.6)\n\t)\n"
        '\t(paper "A4")\n'
        "\t(layers\n" + _LAYERS + "\n\t)\n"
        "\t(setup\n\t\t(pad_to_mask_clearance 0)\n\t)\n"
        + net_decls + "\n"
        + "\n".join(fp_blocks) + ("\n" if fp_blocks else "")
        + outline + "\n"
        ")\n"
    )
