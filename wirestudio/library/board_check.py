"""Check a board YAML before it joins the library.

The board counterpart of `check.py`. A board is pin data more than
anything, so most of the checks are cross-references: every pin a bus,
onboard peripheral or radio names is one of the board's GPIOs, the KiCad
symbol has the pins `pin_map` binds, the enclosure's ports and holes sit on
the PCB. Then the board's onboard peripherals are seeded into a design and
rendered to ESPHome YAML, the way a user's first design on it would be.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from wirestudio.csp.compatibility import check_pin_compatibility
from wirestudio.enclosure import EnclosureUnavailable, generate_scad
from wirestudio.generate.yaml_gen import render_yaml
from wirestudio.kicad.importer import default_symbol_dirs
from wirestudio.kicad.symbol_parser import load_symbols, resolve_symbol
from wirestudio.library import Library, LibraryBoard
from wirestudio.library.check import _FOOTPRINT_ENV_VARS, _ID_RE
from wirestudio.model import Design
from wirestudio.seed import seed_onboard_components

NOT_CHECKED = [
    "the pinout itself: pins are checked against each other and the KiCad symbol, not against the datasheet",
    "ESPHome schema: the YAML renders, but only `esphome config` proves the keys",
    "enclosure solid: the .scad generates, but only scripts/check_enclosures.py renders it in OpenSCAD",
]

_ESP32_VARIANTS = {
    "esp32", "esp32s2", "esp32s3", "esp32c2", "esp32c3", "esp32c5", "esp32c6",
    "esp32c61", "esp32h2", "esp32p4",
}
_OTHER_PLATFORMS = {"esp8266", "rp2040", "bk72xx", "rtl87xx", "ln882x", "nrf52"}
_FRAMEWORKS = {"arduino", "esp-idf"}
_BUS_LINES = {
    "i2c": ("sda", "scl"), "spi": ("clk", "mosi", "miso"),
    "uart": ("tx", "rx"), "i2s": ("bclk", "lrclk"),
}
# The lines an MCU drives; an input-only GPIO cannot carry them.
_DRIVEN_LINES = {"sda", "scl", "clk", "mosi", "tx", "bclk", "lrclk"}
_EDGES = {"short_a": "length", "short_b": "length", "long_a": "width", "long_b": "width"}


@dataclass
class BoardCheck:
    ok: bool
    library_id: str = ""
    exists: str = ""  # "" | bundled | user
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    not_checked: list[str] = field(default_factory=lambda: list(NOT_CHECKED))
    verified: list[str] = field(default_factory=list)
    board: Optional[LibraryBoard] = None
    saved: str = ""

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "library_id": self.library_id, "exists": self.exists,
            "errors": self.errors, "warnings": self.warnings,
            "unverified": self.unverified, "not_checked": self.not_checked,
            "verified": self.verified, "saved": self.saved,
        }


def check_board_yaml(text: str, library: Library) -> BoardCheck:
    report = BoardCheck(ok=False)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        report.errors.append(f"not valid YAML: {e}")
        return report
    if not isinstance(data, dict):
        report.errors.append("top level must be a mapping with id, name, mcu, chip_variant, platformio_board")
        return report
    try:
        board = LibraryBoard.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"]) or "<root>"
            report.errors.append(f"{loc}: {err['msg']}")
        report.library_id = str(data.get("id", ""))
        return report

    report.library_id = board.id
    report.board = board
    report.exists = library.board_source(board.id)
    if not _ID_RE.match(board.id):
        report.errors.append(
            f"id {board.id!r} must be lowercase letters, digits, '_' or '-' (it names the file)")
    _check_platform(board, report)
    _check_board_key(board, report)
    _check_rails(board, report)
    _check_pins(board, report)
    _check_kicad(board, report)
    _check_enclosure(board, library, report)
    _check_render(board, library, report)
    report.ok = not report.errors
    return report


def create_board(text: str, library: Library, *, overwrite: bool = False) -> BoardCheck:
    """Check, then save into the user library. Never touches a bundled id."""
    report = check_board_yaml(text, library)
    if not report.ok:
        return report
    if report.exists == "bundled":
        report.errors.append(f"'{report.library_id}' is a bundled board; pick another id")
    elif report.exists == "user" and not overwrite:
        report.errors.append(f"'{report.library_id}' already exists in the user library; pass overwrite")
    if report.errors:
        report.ok = False
        return report
    try:
        report.saved = str(library.save_board(report.library_id, text))
    except PermissionError as e:
        report.ok = False
        report.errors.append(str(e))
    return report


def _check_platform(board: LibraryBoard, report: BoardCheck) -> None:
    variant = board.chip_variant
    if variant.startswith("esp32"):
        if variant not in _ESP32_VARIANTS:
            report.errors.append(
                f"chip_variant {variant!r} is not an ESP32 variant ESPHome knows "
                f"({', '.join(sorted(_ESP32_VARIANTS))})")
        if board.mcu != "esp32":
            report.errors.append(f"chip_variant {variant} needs mcu esp32, not {board.mcu}")
    elif variant not in _OTHER_PLATFORMS:
        report.errors.append(
            f"chip_variant {variant!r} is not an ESPHome platform "
            f"({', '.join(sorted(_ESP32_VARIANTS | _OTHER_PLATFORMS))})")
    elif board.mcu != variant:
        report.errors.append(f"chip_variant {variant} needs mcu {variant}, not {board.mcu}")
    if board.framework not in _FRAMEWORKS:
        report.errors.append(f"framework {board.framework!r} must be one of {', '.join(sorted(_FRAMEWORKS))}")


def _check_board_key(board: LibraryBoard, report: BoardCheck) -> None:
    """`platformio_board` against ESPHome's own board tables, when ESPHome
    is installed. ESPHome builds an unknown key on the variant alone, so
    that is a warning; a known key on another chip is an error."""
    try:
        if board.chip_variant.startswith("esp32"):
            from esphome.components.esp32.boards import BOARDS
        elif board.chip_variant == "esp8266":
            from esphome.components.esp8266.boards import BOARDS
        else:
            return
    except ImportError:
        report.unverified.append("platformio_board not looked up: ESPHome is not installed here")
        return
    info = BOARDS.get(board.platformio_board)
    if info is None:
        report.warnings.append(
            f"platformio_board {board.platformio_board!r} is not in ESPHome's {board.mcu} board list; "
            "ESPHome falls back to the chip variant, and PlatformIO must still know the key")
        return
    variant = str(info.get("variant", "")).lower()
    if variant and variant != board.chip_variant:
        report.errors.append(
            f"platformio_board {board.platformio_board!r} is an {variant} board in ESPHome, "
            f"not {board.chip_variant}")
        return
    report.verified.append(f"platformio_board {board.platformio_board} is an ESPHome {board.mcu} board")


def _check_rails(board: LibraryBoard, report: BoardCheck) -> None:
    names = [r.name for r in board.rails]
    for name in sorted({n for n in names if names.count(n) > 1}):
        report.errors.append(f"rail {name!r} is declared twice")
    if "GND" not in names:
        report.errors.append("no GND rail: every ground pin in a design connects to it")
    if not any(r.voltage > 0 for r in board.rails):
        report.errors.append("no supply rail (a rail with voltage above 0)")


def _check_pins(board: LibraryBoard, report: BoardCheck) -> None:
    caps = board.gpio_capabilities
    if not caps:
        report.errors.append("gpio_capabilities is empty: nothing can be wired to this board")
        return

    def need(pin, where: str) -> bool:
        if pin not in caps:
            report.errors.append(f"{where}: {pin} is not in gpio_capabilities")
            return False
        return True

    for bus_type, spec in board.default_buses.items():
        lines = _BUS_LINES.get(bus_type)
        if lines is None:
            report.errors.append(
                f"default_buses.{bus_type}: unknown bus type ({', '.join(_BUS_LINES)})")
            continue
        if not isinstance(spec, dict):
            report.errors.append(f"default_buses.{bus_type} must map lines to pins")
            continue
        for line in lines:
            if line not in spec and not (bus_type == "spi" and line == "miso"):
                report.errors.append(f"default_buses.{bus_type}: no {line} pin")
        for line, pin in spec.items():
            if line not in lines:
                continue
            if need(pin, f"default_buses.{bus_type}.{line}") and line in _DRIVEN_LINES \
                    and "input_only" in caps[pin]:
                report.errors.append(
                    f"default_buses.{bus_type}.{line}: {pin} is input_only and cannot drive {line}")

    for name, params in board.onboard_peripherals.items():
        if not isinstance(params, dict):
            report.errors.append(f"onboard_peripherals.{name} must be a mapping")
            continue
        for key, value in params.items():
            if isinstance(value, str) and key != "address":
                need(value, f"onboard_peripherals.{name}.{key}")

    if board.radio is not None:
        radio = board.radio
        for key, pin in radio.pins.model_dump(exclude_none=True).items():
            need(pin, f"radio.pins.{key}")
        for key in ("setup_high", "setup_low"):
            for pin in getattr(radio, key):
                need(pin, f"radio.{key}")
        for key in ("txen", "rxen"):
            if getattr(radio, key):
                need(getattr(radio, key), f"radio.{key}")


def _check_kicad(board: LibraryBoard, report: BoardCheck) -> None:
    ref = board.kicad
    if ref is None:
        report.warnings.append("no kicad: block: the schematic and PCB leave the board out")
        return
    rails = {r.name for r in board.rails}
    if not ref.pin_map:
        report.warnings.append("no kicad.pin_map: the board's pins stay unconnected on the schematic and PCB")
    for role in ref.pin_map:
        if role not in board.gpio_capabilities and role not in rails:
            report.warnings.append(
                f"kicad.pin_map.{role}: not in gpio_capabilities or rails, so no design wires it")
    unmapped = [g for g in board.gpio_capabilities if g not in ref.pin_map]
    if ref.pin_map and unmapped:
        report.warnings.append(
            f"GPIOs with no kicad.pin_map entry, unconnected on the PCB: {', '.join(unmapped)}")

    symbol_dirs = [d for d in default_symbol_dirs() if d.is_dir()]
    path = next((d / f"{ref.symbol_lib}.kicad_sym" for d in symbol_dirs
                 if (d / f"{ref.symbol_lib}.kicad_sym").is_file()), None)
    if not symbol_dirs:
        report.unverified.append("KiCad symbol not checked: no symbol library found (set KICAD8_SYMBOL_DIR)")
    elif path is None:
        report.errors.append(f"kicad: symbol library {ref.symbol_lib!r} not found")
    else:
        symbols = load_symbols(path)
        if ref.symbol not in symbols:
            report.errors.append(f"kicad: no symbol {ref.symbol!r} in {ref.symbol_lib}")
        else:
            pins = resolve_symbol(symbols, ref.symbol).pins
            known = {p[0] for p in pins if p[0]} | {p[1] for p in pins if p[1]}
            report.verified.append(f"KiCad symbol {ref.symbol_lib}:{ref.symbol} has every pin_map pin")
            for role, pin in ref.pin_map.items():
                if pin not in known:
                    report.errors.append(
                        f"kicad.pin_map.{role}: {ref.symbol_lib}:{ref.symbol} has no pin {pin!r}")
            taken: dict[str, str] = {}
            for role, pin in ref.pin_map.items():
                if pin in taken:
                    report.errors.append(
                        f"kicad.pin_map: {role} and {taken[pin]} share pin {pin}, which would short them")
                taken.setdefault(pin, role)

    if not ref.footprint:
        report.warnings.append("no kicad.footprint: the PCB places no board footprint")
        return
    fp_dir = next((Path(os.environ[v]) for v in _FOOTPRINT_ENV_VARS
                   if os.environ.get(v) and Path(os.environ[v]).is_dir()), None)
    if fp_dir is None:
        report.unverified.append(
            "KiCad footprint not checked: no footprint library found (set KICAD8_FOOTPRINT_DIR)")
    elif ":" not in ref.footprint:
        report.errors.append(f"kicad.footprint {ref.footprint!r} must be LIB:NAME")
    else:
        lib, name = ref.footprint.split(":", 1)
        if (fp_dir / f"{lib}.pretty" / f"{name}.kicad_mod").is_file():
            report.verified.append(f"KiCad footprint {ref.footprint} exists")
        else:
            report.errors.append(f"kicad.footprint {ref.footprint!r} not in the KiCad footprint library")


def _check_enclosure(board: LibraryBoard, library: Library, report: BoardCheck) -> None:
    enc = board.enclosure
    if enc is None:
        report.warnings.append("no enclosure: block: no parametric shell for this board")
        return
    pcb = enc.pcb
    if pcb.length_mm <= 0 or pcb.width_mm <= 0 or pcb.thickness_mm <= 0:
        report.errors.append("enclosure.pcb: length, width and thickness must be positive")
        return
    for i, hole in enumerate(enc.mount_holes):
        r = hole.hole_diameter_mm / 2
        if not (r <= hole.x_mm <= pcb.length_mm - r and r <= hole.y_mm <= pcb.width_mm - r):
            report.errors.append(
                f"enclosure.mount_holes[{i}]: ({hole.x_mm}, {hole.y_mm}) is off the "
                f"{pcb.length_mm} x {pcb.width_mm} PCB")
    for i, port in enumerate(enc.ports):
        if port.edge not in _EDGES:
            report.errors.append(f"enclosure.ports[{i}]: edge {port.edge!r} must be one of {', '.join(_EDGES)}")
            continue
        span = pcb.width_mm if _EDGES[port.edge] == "length" else pcb.length_mm
        if port.offset_mm < 0 or port.offset_mm + port.width_mm > span:
            report.errors.append(
                f"enclosure.ports[{i}]: {port.kind} at {port.offset_mm} + {port.width_mm} "
                f"runs off the {span} mm {port.edge} edge")
    try:
        generate_scad(_design(board, {}), _probe(board, library))
    except EnclosureUnavailable as e:
        report.errors.append(f"enclosure: the generator refused it: {e}")
        return
    report.verified.append(f"enclosure .scad generates for the {pcb.length_mm} x {pcb.width_mm} mm PCB")


def _check_render(board: LibraryBoard, library: Library, report: BoardCheck) -> None:
    """Seed the onboard peripherals and render the design ESPHome YAML."""
    probe = _probe(board, library)
    try:
        design, notes = seeded_design(board, probe)
    except ValidationError as e:
        report.errors.append(f"the onboard peripherals do not make a valid design: {e.errors()[0]['msg']}")
        return
    report.warnings.extend(notes)
    try:
        rendered = render_yaml(design, probe)
    except (ValueError, TypeError, KeyError, FileNotFoundError, yaml.YAMLError) as e:
        report.errors.append(f"ESPHome YAML does not render for this board: {e}")
        return
    if not rendered.strip():
        report.errors.append("ESPHome YAML renders empty")
        return
    seeded = ", ".join(c.library_id for c in design.components) or "no onboard peripherals"
    report.verified.append(f"ESPHome YAML renders with {seeded}")
    for w in check_pin_compatibility(design.model_dump(mode="json"), probe):
        if w.severity == "error":
            report.errors.append(f"onboard {w.component_id}.{w.pin_role} on {w.pin}: {w.message}")


def seeded_design(board: LibraryBoard, library: Library) -> tuple[Design, list[str]]:
    """A new design on the board with its onboard peripherals seeded, and
    the seeder's notes on any it skipped. `library` must resolve the board."""
    frag = seed_onboard_components(board, library)
    return _design(board, frag), [w["text"] for w in frag["warnings"]]


def _probe(board: LibraryBoard, library: Library) -> Library:
    probe = Library(library.root, library.user_dir)
    probe.register_board(board)
    return probe


def _design(board: LibraryBoard, frag: dict) -> Design:
    return Design.model_validate({
        "schema_version": "0.1", "id": "board-check", "name": "board check",
        "board": {"library_id": board.id, "mcu": board.mcu, "framework": board.framework},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": frag.get("components", []), "buses": frag.get("buses", []),
        "connections": frag.get("connections", []), "requirements": [], "warnings": [],
    })
