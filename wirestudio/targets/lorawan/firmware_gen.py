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

# Hardware UARTs a fragment may claim; UART0 stays the console.
_UARTS = {"esp32": 2, "esp32s3": 2}


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
        "setup_high": [_pin(p) for p in radio.setup_high],
        "setup_low": [_pin(p) for p in radio.setup_low],
        "txen": _pin(radio.txen) if radio.txen else None,
        "rxen": _pin(radio.rxen) if radio.rxen else None,
    }





def _wiring_for(component_id: str, design: Design) -> tuple[dict, Optional[dict], Optional[str]]:
    """Resolved GPIO pins (by role), bus and hub for a component, from the
    design's physical connections -- the path a user-authored component uses.
    Synthesized onboard peripherals have no connections and fall back to their
    params."""
    pins: dict[str, int] = {}
    bus: Optional[dict] = None
    parent: Optional[str] = None
    for conn in design.connections:
        if conn.component_id != component_id:
            continue
        t = conn.target
        if t.kind == "gpio":
            pins[conn.pin_role] = _pin(t.pin)
        elif t.kind == "component":
            parent = t.component_id
        elif t.kind == "bus":
            for b in design.buses:
                if b.id == t.bus_id:
                    bus = {"id": b.id, "sda": _pin(b.sda), "scl": _pin(b.scl),
                           "rx": _pin(b.rx), "tx": _pin(b.tx), "pin": _pin(b.pin),
                           "clk": _pin(b.clk), "miso": _pin(b.miso), "mosi": _pin(b.mosi),
                           "baud": b.baud_rate, "parity": b.parity or "NONE"}
                    break
    return pins, bus, parent


def component_fragments(design: Design, library: Library) -> list[dict]:
    """Each component's `lorawan:` C++ rendered for this design, in emission
    order: its id, the library deps and shared prerequisites it needs, and
    its globals, setup and loop fragments. Raises ValueError when the design
    asks for more hardware UARTs than the chip has, or puts an SPI part on
    pins other than the radio's."""
    board = library.board(design.board.library_id)
    # One inventory for both the payload (codec.fields_for) and the firmware
    # fragments: the design's components plus synthesized onboard
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

    out: list[dict] = []
    uarts: dict[str, int] = {}
    radio_spi = (board.default_buses or {}).get("spi") or {}

    for comp_inst in components:
        lib_comp = library.component(comp_inst.library_id)
        spec = lib_comp.lorawan
        if spec is None:
            continue
        pins, bus, parent = _wiring_for(comp_inst.id, design)
        serial = None
        if "uart" in spec.requires:
            key = bus["id"] if bus else comp_inst.id
            if key not in uarts:
                if len(uarts) >= _UARTS.get(board.chip_variant, 1):
                    raise ValueError(
                        f"{comp_inst.id}: the lorawan firmware has {_UARTS.get(board.chip_variant, 1)} "
                        f"hardware UART(s) to give on {board.chip_variant}, already taken by "
                        f"{', '.join(uarts)}"
                    )
                uarts[key] = len(uarts) + 1
            serial = uarts[key]
        if "spi" in spec.requires and bus is not None:
            # The fragments share the radio's SPI bus (RadioLib drives the
            # global SPI), so a part on other pins would re-pin the radio.
            wanted = {k: _pin(radio_spi.get(k)) for k in ("clk", "miso", "mosi")}
            got = {k: bus[k] for k in wanted if bus[k] is not None}
            if any(wanted[k] != v for k, v in got.items()):
                raise ValueError(
                    f"{comp_inst.id}: SPI parts share the radio's bus on the lorawan target "
                    f"(clk/miso/mosi {wanted['clk']}/{wanted['miso']}/{wanted['mosi']} on "
                    f"{board.id}); bus {bus['id']} is on other pins"
                )
        render_ctx = {
            "id": comp_inst.id,
            "label": comp_inst.label,
            "params": comp_inst.params,
            "pin": next(iter(pins.values()), None),
            "pins": pins,
            "bus": bus,
            "serial": serial,
            "parent": parent,
            "radio_spi": {k: _pin(v) for k, v in radio_spi.items()},
            "onboard": onboard,
            "board": board,
            "i2c_sda": i2c_sda,
            "i2c_scl": i2c_scl,
            **flags,
        }
        out.append({
            "id": comp_inst.id,
            "lib_deps": spec.lib_deps,
            "requires": spec.requires,
            **{part: _frag_jinja.from_string(getattr(spec, part)).render(**render_ctx)
               for part in ("globals", "setup", "loop") if getattr(spec, part)},
        })
    return out


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

    frags = component_fragments(design, library)
    lib_deps = list(dict.fromkeys(dep for f in frags for dep in f["lib_deps"]))
    i2c = (board.default_buses or {}).get("i2c", {})
    i2c_sda, i2c_scl = _pin(i2c.get("sda")), _pin(i2c.get("scl"))

    ctx = {
        "device_name": device_name,
        "board": {
            "platformio_board": board.platformio_board,
            "chip_variant": board.chip_variant,
            "mcu": board.mcu,
            "flash_size_mb": design.board.flash_size_mb or board.flash_size_mb,
        },
        "region": region,
        "sub_band": sub_band,
        "sub_band_index": sub_band - 1,
        "join_eui": join_eui,
        "payload_size": size,
        "min_datarate": min_datarate,
        "payload_pack": pack_cpp(fields),
        "component_lib_deps": lib_deps,
        "component_requires": list({r for f in frags for r in f["requires"]}),
        "component_globals": "\n".join(f["globals"] for f in frags if "globals" in f),
        "component_setup": "\n".join(f["setup"] for f in frags if "setup" in f),
        "component_loop": "\n".join(f["loop"] for f in frags if "loop" in f),
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
