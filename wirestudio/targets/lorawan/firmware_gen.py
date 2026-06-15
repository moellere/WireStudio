"""LoRaWAN firmware generator: a pure function from a design (+ library) to a
PlatformIO project (RadioLib + LoRaWAN_ESP32).

Generic over *credentials* (those arrive at runtime via serial provisioning in
Phase 6), not over peripherals. The board's ``radio:`` block is the load-bearing
input: it picks the RadioLib module class and the wiring constructor, and pins
the US915 sub-band so joins land on channels the gateway hears.

Only jinja2 + the library are needed -- no LoRaWAN runtime deps -- so this is
importable without the ``lorawan`` extra.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from wirestudio.library import Library, Radio
from wirestudio.model import Design
from wirestudio.targets.lorawan.codec import (
    _pin,
    fields_for,
    pack_cpp,
    payload_size,
    resolve_components,
)

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_jinja = Environment(
    loader=FileSystemLoader(str(_TEMPLATES)),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)

# Separate env for the per-component C++ fragments carried in library YAML.
# Plain (non-strict) so a fragment's `| default(...)` and missing-attr accesses
# behave, while a genuine template syntax error still raises.
_frag_jinja = Environment()

_REGION_DEFAULT = "US915"
_SUBBAND_DEFAULT = 2

# C++ fragment emission order (stable sort key): the PMIC powers the GPS/LoRa
# rails so it initializes first; the OLED status display reads the other
# sensors' globals so it emits last. Everything else keeps its inventory order.
_SETUP_PRIORITY = {"axp192": 0, "ssd1306": 2}


def _emit_priority(component) -> int:
    return _SETUP_PRIORITY.get(component.library_id, 1)


def _radio_ctx(radio: Radio) -> dict:
    is_sx126x = radio.chip == "sx1262"
    cs, rst = _pin(radio.pins.cs), _pin(radio.pins.rst)
    dio0, dio1, busy = _pin(radio.pins.dio0), _pin(radio.pins.dio1), _pin(radio.pins.busy)
    # RadioLib Module(cs, irq, rst, gpio): SX127x drives DIO0 (irq) + optional
    # DIO1 (gpio); SX126x drives DIO1 (irq) + BUSY (gpio).
    irq = dio1 if is_sx126x else dio0
    gpio = busy if is_sx126x else (dio1 if dio1 is not None else "RADIOLIB_NC")
    return {
        "radiolib_class": radio.radiolib_class,
        "is_sx126x": is_sx126x,
        "cs": cs,
        "rst": rst,
        "irq": irq,
        "gpio": gpio,
        "tcxo_voltage": radio.tcxo_voltage,
        "dio2_as_rf_switch": radio.dio2_as_rf_switch,
    }





def _wiring_for(component_id: str, design: Design) -> tuple[dict, Optional[dict]]:
    """Resolved GPIO pins (by role) and bus for a component, from the design's
    physical connections -- the path a user-authored component uses. Synthesized
    onboard peripherals have no connections and fall back to their params."""
    pins: dict[str, int] = {}
    bus: Optional[dict] = None
    for conn in design.connections:
        if conn.component_id != component_id:
            continue
        t = conn.target
        if t.kind == "gpio":
            pins[conn.pin_role] = _pin(t.pin)
        elif t.kind == "bus":
            for b in design.buses:
                if b.id == t.bus_id:
                    bus = {"id": b.id, "sda": _pin(b.sda), "scl": _pin(b.scl),
                           "rx": _pin(b.rx), "tx": _pin(b.tx), "baud": b.baud_rate}
                    break
    return pins, bus


def generate_firmware(design: Design, library: Library) -> dict[str, str]:
    """Return the PlatformIO project as a {relative_path: contents} map.

    Raises FileNotFoundError for an unknown board and ValueError when the board
    carries no radio (the lorawan target only offers radio boards, but the
    generator validates the boundary regardless).
    """
    board = library.board(design.board.library_id)
    if board.radio is None:
        raise ValueError(
            f"board {board.id!r} has no radio: block; the lorawan firmware "
            "generator needs an SX127x or SX126x board"
        )
    lw = design.lorawan
    region = lw.region if lw else _REGION_DEFAULT
    sub_band = lw.sub_band if lw else _SUBBAND_DEFAULT
    join_eui = (lw.join_eui if lw and lw.join_eui else "0000000000000000").lower()
    device_name = (
        design.fleet.device_name
        if design.fleet and design.fleet.device_name
        else design.id
    )
    fields = fields_for(design, library)
    size = payload_size(fields)
    # US915 per-DR app-payload caps: DR0 (SF10) = 11 B, DR1/2 (SF9/8) = 53 B,
    # DR3 (SF7) = 242 B. Pick the lowest DR (longest range) that fits so the
    # first post-join uplink isn't rejected as too long; ADR tunes from there.
    min_datarate = 0 if size <= 11 else (1 if size <= 53 else 3)

    # One inventory for both the payload (above, via codec.fields_for) and the
    # firmware fragments below: the design's components plus synthesized onboard
    # peripherals. resolve_components returns payload order; emit the C++
    # fragments in hardware-init order instead -- the PMIC powers the GPS/LoRa
    # rails so it must initialize first, and the OLED status display reads the
    # other sensors so it goes last.
    components = sorted(resolve_components(design, library), key=_emit_priority)
    onboard = board.onboard_peripherals or {}
    i2c = (board.default_buses or {}).get("i2c", {})
    i2c_sda, i2c_scl = _pin(i2c.get("sda")), _pin(i2c.get("scl"))

    # Presence flags fragments key off (e.g. the OLED status display shows a GPS
    # line only when a GPS is also present).
    by_lib = {c.library_id for c in components}
    flags = {
        "has_gps": "uart_gps" in by_lib,
        "has_axp": "axp192" in by_lib,
        "has_dht": "dht" in by_lib,
        "has_oled": "ssd1306" in by_lib,
    }

    component_lib_deps: list[str] = []
    component_requires: set[str] = set()
    component_globals: list[str] = []
    component_setup: list[str] = []
    component_loop: list[str] = []

    for comp_inst in components:
        lib_comp = library.component(comp_inst.library_id)
        spec = lib_comp.lorawan
        if spec is None:
            continue
        for dep in spec.lib_deps:
            if dep not in component_lib_deps:
                component_lib_deps.append(dep)
        component_requires.update(spec.requires)

        pins, bus = _wiring_for(comp_inst.id, design)
        render_ctx = {
            "id": comp_inst.id,
            "label": comp_inst.label,
            "params": comp_inst.params,
            "pin": next(iter(pins.values()), None),
            "pins": pins,
            "bus": bus,
            "onboard": onboard,
            "board": board,
            "i2c_sda": i2c_sda,
            "i2c_scl": i2c_scl,
            **flags,
        }
        if spec.globals:
            component_globals.append(_frag_jinja.from_string(spec.globals).render(**render_ctx))
        if spec.setup:
            component_setup.append(_frag_jinja.from_string(spec.setup).render(**render_ctx))
        if spec.loop:
            component_loop.append(_frag_jinja.from_string(spec.loop).render(**render_ctx))

    ctx = {
        "device_name": device_name,
        "board": {
            "platformio_board": board.platformio_board,
            "chip_variant": board.chip_variant,
            "mcu": board.mcu,
        },
        "region": region,
        "sub_band": sub_band,
        "sub_band_index": sub_band - 1,
        "join_eui": join_eui,
        "payload_size": size,
        "min_datarate": min_datarate,
        "payload_pack": pack_cpp(fields),
        "component_lib_deps": component_lib_deps,
        "component_requires": list(component_requires),
        "component_globals": "\n".join(component_globals),
        "component_setup": "\n".join(component_setup),
        "component_loop": "\n".join(component_loop),
        "i2c_sda": i2c_sda,
        "i2c_scl": i2c_scl,
        **_radio_ctx(board.radio),
    }
    return {
        "platformio.ini": _jinja.get_template("platformio.ini.j2").render(**ctx),
        "src/main.cpp": _jinja.get_template("main.cpp.j2").render(**ctx),
    }


def write_firmware(design: Design, library: Library, dest: Path) -> Path:
    """Write the generated project under `dest`. Returns `dest`."""
    dest = Path(dest)
    for rel, contents in generate_firmware(design, library).items():
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    return dest
