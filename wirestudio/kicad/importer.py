"""Import a KiCad library symbol into a wirestudio component's `kicad:` block.

CLI: `python -m wirestudio.kicad.import --symbol Sensor:BME280`.

Default mode prints a draft `kicad:` YAML block to stdout. `--into <id>`
splices that block into an existing `library/components/<id>.yaml`,
preserving the rest of the file verbatim, and derives a `pin_map` by
comparing the component's pin roles against the symbol's pin names.

Closes the hand-write-every-entry tail of library KiCad mapping. The
output is a draft for human review -- the importer can name the symbol
and footprint, but `pin_map` is a best-effort suggestion.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

from wirestudio.kicad.symbol_parser import KicadSymbol, load_symbols, resolve_symbol
from wirestudio.library import KicadSymbolRef, default_library

# Role names that denote the same electrical net under different
# spellings -- used to map a component's power/ground roles onto
# whatever the KiCad symbol happens to call those pins.
_POWER_ALIASES = {"VCC", "VDD", "VIN", "V+", "VS", "PWR", "3V3", "5V",
                  "+3V3", "+5V", "VBAT", "VBUS"}
_GND_ALIASES = {"GND", "VSS", "0V", "AGND", "DGND"}

_BLOCK_COMMENT = "# KiCad symbol mapping (0.9 schematic export)."


def default_symbol_dirs() -> list[Path]:
    """Standard locations a KiCad install drops its stock `.kicad_sym`
    libraries, newest-first, with the KICAD*_SYMBOL_DIR env vars ahead
    of the hard-coded paths."""
    dirs: list[Path] = []
    for var in ("KICAD9_SYMBOL_DIR", "KICAD8_SYMBOL_DIR",
                "KICAD7_SYMBOL_DIR", "KICAD_SYMBOL_DIR"):
        val = os.environ.get(var)
        if val:
            dirs.append(Path(val))
    dirs += [
        Path("/usr/share/kicad/symbols"),
        Path("/usr/local/share/kicad/symbols"),
        Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"),
        Path("C:/Program Files/KiCad/9.0/share/kicad/symbols"),
        Path("C:/Program Files/KiCad/8.0/share/kicad/symbols"),
    ]
    return dirs


def find_symbol_lib(lib_name: str, search_dirs: list[Path]) -> Path:
    fname = f"{lib_name}.kicad_sym"
    tried: list[str] = []
    for d in search_dirs:
        p = Path(d) / fname
        tried.append(str(p))
        if p.is_file():
            return p
    raise FileNotFoundError(
        f"could not find {fname}; looked in:\n  " + "\n  ".join(tried)
        + "\npass --symbol-dir to point at your KiCad symbol library directory"
    )


def build_kicad_dict(
    lib_name: str, symbol: KicadSymbol, pin_map: dict[str, str] | None = None,
) -> dict:
    """Build the `kicad:` mapping dict (ordered for stable YAML output)."""
    d: dict = {"symbol_lib": lib_name, "symbol": symbol.name}
    footprint = symbol.properties.get("Footprint", "").strip()
    if footprint:
        d["footprint"] = footprint
    if pin_map:
        d["pin_map"] = dict(pin_map)
    KicadSymbolRef.model_validate(d)  # boundary check before we emit/write
    return d


def suggest_pin_map(symbol: KicadSymbol, roles: list[str]) -> dict[str, str]:
    """Map component pin roles onto symbol pin names. Roles whose name
    matches a symbol pin exactly are left out (they pass through
    unchanged); only genuine renames land in the result."""
    pin_names = [p[0] for p in symbol.pins if p[0]]
    exact = set(pin_names)
    by_upper = {p.upper(): p for p in pin_names}
    out: dict[str, str] = {}
    for role in roles:
        if role in exact:
            continue
        hit = by_upper.get(role.upper())
        if hit is not None:
            if hit != role:
                out[role] = hit
            continue
        klass = None
        if role.upper() in _POWER_ALIASES:
            klass = _POWER_ALIASES
        elif role.upper() in _GND_ALIASES:
            klass = _GND_ALIASES
        if klass is not None:
            cand = next((p for p in pin_names if p.upper() in klass), None)
            if cand is not None and cand != role:
                out[role] = cand
    return out


def render_block(kicad_dict: dict) -> str:
    """Render the `kicad:` block as YAML text (key order preserved)."""
    return yaml.safe_dump({"kicad": kicad_dict}, sort_keys=False).rstrip() + "\n"


def component_pin_roles(component_path: Path) -> list[str]:
    data = yaml.safe_load(component_path.read_text()) or {}
    pins = (data.get("electrical") or {}).get("pins") or []
    return [p["role"] for p in pins if isinstance(p, dict) and "role" in p]


def apply_to_component(component_path: Path, kicad_dict: dict) -> None:
    """Splice the `kicad:` block into a component YAML in place.

    Textual splice rather than load/dump so hand-written comments,
    key order, and formatting in the rest of the file survive. An
    existing top-level `kicad:` block (and its mapping comment) is
    replaced; otherwise the block is appended.
    """
    lines = component_path.read_text().splitlines()
    block = [_BLOCK_COMMENT, *render_block(kicad_dict).splitlines()]

    start = next(
        (i for i, ln in enumerate(lines) if ln == "kicad:" or ln.startswith("kicad:")),
        None,
    )
    if start is not None:
        s = start
        if s > 0 and lines[s - 1].lstrip().startswith("# KiCad symbol mapping"):
            s -= 1
        e = start + 1
        while e < len(lines) and (not lines[e].strip() or lines[e][:1] in (" ", "\t")):
            e += 1
        new_lines = lines[:s] + block + lines[e:]
    else:
        sep = [""] if lines and lines[-1].strip() else []
        new_lines = lines + sep + block

    component_path.write_text("\n".join(new_lines) + "\n")


def _print_pin_report(
    symbol: KicadSymbol, roles: list[str] | None, pin_map: dict[str, str] | None,
) -> None:
    pins = [p for p in symbol.pins if p[0] or p[1]]
    print(f"# {symbol.name}: {len(pins)} pins", file=sys.stderr)
    for name, number in pins:
        print(f"#   {number or '?':>3}  {name or '(unnamed)'}", file=sys.stderr)
    if roles is None:
        print("# no component targeted -- review pin_map by hand against the "
              "roles above", file=sys.stderr)
        return
    mapped = pin_map or {}
    pin_names = {p[0] for p in symbol.pins if p[0]}
    unresolved = [r for r in roles if r not in pin_names and r not in mapped]
    if mapped:
        print("# suggested pin_map: "
              + ", ".join(f"{k}->{v}" for k, v in mapped.items()), file=sys.stderr)
    if unresolved:
        print("# UNRESOLVED roles (no symbol pin matched -- fix pin_map "
              "manually): " + ", ".join(unresolved), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wirestudio.kicad.import",
        description="Import a KiCad library symbol into a component's kicad: block.",
    )
    parser.add_argument(
        "--symbol", required=True, metavar="LIB:SYMBOL",
        help="KiCad symbol to import, e.g. Sensor:BME280",
    )
    parser.add_argument(
        "--symbol-dir", action="append", metavar="DIR",
        help="directory of .kicad_sym files (repeatable); "
             "defaults to standard KiCad install paths",
    )
    parser.add_argument(
        "--into", metavar="COMPONENT_ID",
        help="splice the kicad: block into library/components/<id>.yaml "
             "and derive a pin_map from its pin roles",
    )
    args = parser.parse_args(argv)

    if ":" not in args.symbol:
        parser.error("--symbol must be LIB:SYMBOL, e.g. Sensor:BME280")
    lib_name, _, symbol_name = args.symbol.partition(":")

    search = [Path(d) for d in args.symbol_dir] if args.symbol_dir else default_symbol_dirs()
    try:
        lib_path = find_symbol_lib(lib_name, search)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    symbols = load_symbols(lib_path)
    if symbol_name not in symbols:
        print(f"error: symbol {symbol_name!r} not in {lib_path}", file=sys.stderr)
        near = sorted(s for s in symbols if symbol_name.lower() in s.lower())
        if near:
            print("did you mean: " + ", ".join(near[:10]), file=sys.stderr)
        return 2
    symbol = resolve_symbol(symbols, symbol_name)

    if args.into:
        components_dir = default_library().root / "components"
        comp_path = components_dir / f"{args.into}.yaml"
        if not comp_path.is_file():
            print(f"error: no component {args.into!r} at {comp_path}", file=sys.stderr)
            return 2
        roles = component_pin_roles(comp_path)
        pin_map = suggest_pin_map(symbol, roles)
        kicad_dict = build_kicad_dict(lib_name, symbol, pin_map)
        apply_to_component(comp_path, kicad_dict)
        print(f"updated {comp_path}")
        _print_pin_report(symbol, roles, pin_map)
    else:
        kicad_dict = build_kicad_dict(lib_name, symbol)
        print(render_block(kicad_dict), end="")
        _print_pin_report(symbol, None, None)
    return 0
