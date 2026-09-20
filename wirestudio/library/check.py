"""Check a component YAML before it joins the library.

Written for components an agent drafts at runtime, where the author is
a model and the reviewer is whoever reads the report. The checks are
structural: the file parses and validates, the subcircuit's nets hang
together, the ESPHome template renders against a synthetic design, and
-- when the KiCad libraries are installed -- every symbol, pin name and
footprint the file names actually exists. Nothing here simulates the
circuit; `not_checked` says so on every report.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from jinja2 import Environment, TemplateSyntaxError
from pydantic import ValidationError

from wirestudio.generate.yaml_gen import render_component
from wirestudio.kicad.importer import default_symbol_dirs
from wirestudio.kicad.symbol_parser import KicadSymbol, load_symbols, resolve_symbol
from wirestudio.library import Library, LibraryComponent
from wirestudio.model import Design

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SIGNAL_KINDS = ("digital_in", "digital_out", "analog_in", "analog_out", "pwm", "adc", "spi_cs")
_BUS_KINDS = {
    "i2c_sda": "i2c", "i2c_scl": "i2c",
    "spi_clk": "spi", "spi_mosi": "spi", "spi_miso": "spi",
    "uart_tx": "uart", "uart_rx": "uart",
    "onewire_data": "1wire",
    "i2s_bclk": "i2s", "i2s_lrclk": "i2s", "i2s_dout": "i2s", "i2s_din": "i2s",
}
_BUS_PINS = {
    "i2c": {"sda": "GPIO21", "scl": "GPIO22", "frequency_hz": 100000},
    "spi": {"clk": "GPIO18", "mosi": "GPIO23", "miso": "GPIO19"},
    "uart": {"tx": "GPIO17", "rx": "GPIO16", "baud_rate": 9600},
    "1wire": {},
    "i2s": {},
}
_CHECK_BOARD = "esp32-devkitc-v4"

# What a designator prefix may declare in `requires:`. A `Q` that says
# it is a diode is a typo worth catching before it drives substitution.
_PREFIX_FAMILIES = {
    "Q": ("bjt", "mosfet"), "D": ("diode",), "U": ("ic", "regulator"),
    "VR": ("regulator",), "R": ("resistor",), "C": ("capacitor",),
    "L": ("inductor",), "J": ("connector",),
}

NOT_CHECKED = [
    "electrical behaviour: nothing is simulated; ratings are only compared where requires: declares them",
    "ESPHome schema: the template renders, but only `esphome config` on a design proves the keys",
]

_FOOTPRINT_ENV_VARS = (
    "KICAD8_FOOTPRINT_DIR", "KICAD9_FOOTPRINT_DIR", "KICAD7_FOOTPRINT_DIR",
    "KICAD6_FOOTPRINT_DIR", "KICAD_FOOTPRINT_DIR",
)


@dataclass
class ComponentCheck:
    ok: bool
    library_id: str = ""
    exists: str = ""  # "" | bundled | user
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    not_checked: list[str] = field(default_factory=lambda: list(NOT_CHECKED))
    component: Optional[LibraryComponent] = None
    saved: str = ""

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "library_id": self.library_id, "exists": self.exists,
            "errors": self.errors, "warnings": self.warnings,
            "unverified": self.unverified, "not_checked": self.not_checked,
            "saved": self.saved,
        }


def check_component_yaml(text: str, library: Library) -> ComponentCheck:
    report = ComponentCheck(ok=False)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        report.errors.append(f"not valid YAML: {e}")
        return report
    if not isinstance(data, dict):
        report.errors.append("top level must be a mapping with id, name, category, electrical")
        return report
    try:
        comp = LibraryComponent.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"]) or "<root>"
            report.errors.append(f"{loc}: {err['msg']}")
        report.library_id = str(data.get("id", ""))
        return report

    report.library_id = comp.id
    report.component = comp
    report.exists = library.component_source(comp.id)
    if not _ID_RE.match(comp.id):
        report.errors.append(
            f"id {comp.id!r} must be lowercase letters, digits, '_' or '-' (it names the file)")
    if comp.subcircuit is not None:
        _check_subcircuit(comp, report)
    _check_template(comp, library, report)
    _check_kicad(comp, report)
    report.ok = not report.errors
    return report


def create_component(text: str, library: Library, *, overwrite: bool = False) -> ComponentCheck:
    """Check, then save into the user library. Never touches a bundled id."""
    report = check_component_yaml(text, library)
    if not report.ok:
        return report
    if report.exists == "bundled":
        report.errors.append(f"'{report.library_id}' is a bundled component; pick another id")
    elif report.exists == "user" and not overwrite:
        report.errors.append(f"'{report.library_id}' already exists in the user library; pass overwrite")
    if report.errors:
        report.ok = False
        return report
    try:
        report.saved = str(library.save_component(report.library_id, text))
    except PermissionError as e:
        report.ok = False
        report.errors.append(str(e))
    return report


# ---------------------------------------------------------------------------
# Subcircuit nets
# ---------------------------------------------------------------------------

def _check_subcircuit(comp: LibraryComponent, report: ComponentCheck) -> None:
    roles = [p.role for p in comp.electrical.pins]
    seen_ids: set[str] = set()
    touches: dict[str, list[str]] = {}
    for part in comp.subcircuit.parts:
        if part.id in seen_ids:
            report.errors.append(f"subcircuit part id {part.id!r} is declared twice")
        seen_ids.add(part.id)
        if not re.match(r"^[A-Z]+$", part.ref_prefix):
            report.errors.append(
                f"part {part.id}: ref_prefix {part.ref_prefix!r} must be capital letters (Q, R, C, J)")
        if not part.pins:
            report.errors.append(f"part {part.id}: no pins mapped")
        for pin, net in part.pins.items():
            touches.setdefault(net, []).append(f"{part.id}.{pin}")
        if not part.kicad.value:
            report.warnings.append(
                f"part {part.id}: no kicad.value, the BOM and inventory check will see the symbol name")
        if part.requires is not None:
            allowed = _PREFIX_FAMILIES.get(part.ref_prefix)
            if allowed and part.requires.family not in allowed:
                report.warnings.append(
                    f"part {part.id}: requires.family {part.requires.family!r} does not fit "
                    f"designator prefix {part.ref_prefix} ({' or '.join(allowed)})")
    for net, pins in touches.items():
        if net in roles:
            continue
        if len(pins) < 2:
            report.warnings.append(
                f"internal net {net!r} is touched only by {pins[0]}: dangling, or a misspelt pin role")
    for role in roles:
        if role not in touches:
            report.warnings.append(
                f"pin role {role!r} is not connected to any subcircuit part")


# ---------------------------------------------------------------------------
# ESPHome template
# ---------------------------------------------------------------------------

def _check_template(comp: LibraryComponent, library: Library, report: ComponentCheck) -> None:
    template = comp.esphome.yaml_template
    if not template.strip():
        report.warnings.append("esphome.yaml_template is empty: the component emits no ESPHome config")
        return
    try:
        Environment().parse(template)
    except TemplateSyntaxError as e:
        report.errors.append(f"esphome.yaml_template line {e.lineno}: {e.message}")
        return
    if any(p.kind == "hub_ref" for p in comp.electrical.pins):
        report.unverified.append(
            "template not rendered: the component hangs off a parent hub, which a synthetic design cannot supply")
        return
    probe = Library(library.root, library.user_dir)
    probe.register(comp)
    # A bus-kind pin (i2c_sda, spi_clk) usually lands on a design bus, but
    # a template may read it as a bare GPIO instead (the camera drives its
    # own SCCB), so the design is tried both ways before it is an error.
    failures: list[str] = []
    for on_buses in (True, False):
        try:
            design = _synthetic_design(comp, library, on_buses=on_buses)
        except FileNotFoundError as e:
            report.unverified.append(f"template not rendered: {e}")
            return
        try:
            rendered = render_component(design.components[0], design, probe)
        except (ValueError, TypeError, yaml.YAMLError) as e:
            failures.append(str(e))
            continue
        if rendered and not isinstance(rendered, dict):
            report.errors.append("esphome.yaml_template must render to a YAML mapping of ESPHome sections")
        return
    report.errors.append(
        f"esphome.yaml_template does not render against a synthetic design: {failures[0]}")


def _synthetic_design(comp: LibraryComponent, library: Library, *, on_buses: bool) -> Design:
    """One instance of the component on a known board, every signal pin
    on its own GPIO, bus pins on a bus of their type (or on GPIOs when
    `on_buses` is off), power pins on rails, params at their defaults."""
    board = library.board(_CHECK_BOARD)
    gpios = iter(sorted(
        g for g, caps in board.gpio_capabilities.items()
        if "gpio" in caps and "strap" not in caps and "input_only" not in caps))
    connections = []
    buses: dict[str, dict] = {}
    for pin in comp.electrical.pins:
        if pin.kind in _SIGNAL_KINDS or (pin.kind in _BUS_KINDS and not on_buses):
            target = {"kind": "gpio", "pin": next(gpios)}
        elif pin.kind in _BUS_KINDS:
            bus_type = _BUS_KINDS[pin.kind]
            bus = buses.setdefault(bus_type, {"id": f"{bus_type}0", "type": bus_type, **_BUS_PINS[bus_type]})
            target = {"kind": "bus", "bus_id": bus["id"]}
        elif pin.kind == "ground":
            target = {"kind": "rail", "rail": "GND"}
        elif pin.kind == "power":
            target = {"kind": "rail", "rail": "3V3"}
        else:
            continue
        connections.append({"component_id": "dut", "pin_role": pin.role, "target": target})
    params = {
        key: spec["default"] for key, spec in comp.params_schema.items()
        if isinstance(spec, dict) and "default" in spec
    }
    return Design.model_validate({
        "schema_version": "0.1", "id": "component-check", "name": "component check",
        "board": {"library_id": board.id, "mcu": board.mcu, "framework": board.framework},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": [{"id": "dut", "library_id": comp.id, "label": comp.name, "params": params}],
        "buses": list(buses.values()), "requirements": [], "warnings": [],
        "connections": connections,
    })


# ---------------------------------------------------------------------------
# KiCad symbols and footprints
# ---------------------------------------------------------------------------

def _check_kicad(comp: LibraryComponent, report: ComponentCheck) -> None:
    refs = []
    if comp.kicad is not None:
        refs.append(("kicad", comp.kicad, None))
    if comp.subcircuit is not None:
        for part in comp.subcircuit.parts:
            refs.append((f"part {part.id}", part.kicad, part))
    if not refs:
        report.warnings.append("no kicad: block: the schematic, PCB and BOM will skip this component")
        return

    symbol_dirs = [d for d in default_symbol_dirs() if d.is_dir()]
    if not symbol_dirs:
        report.unverified.append(
            "KiCad symbols not checked: no symbol library found (set KICAD8_SYMBOL_DIR)")
    else:
        libs: dict[str, Optional[dict[str, KicadSymbol]]] = {}
        for where, ref, part in refs:
            if ref.symbol_lib not in libs:
                path = next((d / f"{ref.symbol_lib}.kicad_sym" for d in symbol_dirs
                             if (d / f"{ref.symbol_lib}.kicad_sym").is_file()), None)
                libs[ref.symbol_lib] = load_symbols(path) if path else None
            symbols = libs[ref.symbol_lib]
            if symbols is None:
                report.errors.append(f"{where}: symbol library {ref.symbol_lib!r} not found")
                continue
            if ref.symbol not in symbols:
                report.errors.append(f"{where}: no symbol {ref.symbol!r} in {ref.symbol_lib}")
                continue
            sym = resolve_symbol(symbols, ref.symbol)
            names = {p[0] for p in sym.pins if p[0]} | {p[1] for p in sym.pins if p[1]}
            mapped = part.pins.keys() if part is not None else ref.pin_map.values()
            for pin in mapped:
                if pin not in names:
                    report.errors.append(
                        f"{where}: symbol {ref.symbol_lib}:{ref.symbol} has no pin {pin!r} "
                        f"(has {', '.join(sorted(names))})")

    fp_dir = next((Path(os.environ[v]) for v in _FOOTPRINT_ENV_VARS
                   if os.environ.get(v) and Path(os.environ[v]).is_dir()), None)
    if fp_dir is None:
        report.unverified.append(
            "KiCad footprints not checked: no footprint library found (set KICAD8_FOOTPRINT_DIR)")
        return
    for where, ref, _ in refs:
        fp = ref.footprint or ""
        if ":" not in fp:
            report.errors.append(f"{where}: footprint {fp!r} must be LIB:NAME")
            continue
        lib, name = fp.split(":", 1)
        if not (fp_dir / f"{lib}.pretty" / f"{name}.kicad_mod").is_file():
            report.errors.append(f"{where}: footprint {fp!r} not in the KiCad footprint library")
