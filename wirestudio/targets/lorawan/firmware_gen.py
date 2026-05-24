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
from wirestudio.targets.lorawan.codec import fields_for, pack_cpp, payload_size

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_jinja = Environment(
    loader=FileSystemLoader(str(_TEMPLATES)),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)

_REGION_DEFAULT = "US915"
_SUBBAND_DEFAULT = 2


def _pin(value: Optional[str]) -> Optional[int]:
    """Board pins are 'GPIO18'; Arduino wants the bare number 18."""
    if value is None:
        return None
    return int(value.removeprefix("GPIO"))


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


def _sensor_ctx(design: Design, board) -> dict:
    """Template flags + pins for onboard sensors, external GPS, DHT22, and OLED.
    Kept in lockstep with codec.sensors (same onboard keys + lorawan.* configs)."""
    onboard = board.onboard_peripherals or {}
    i2c = (board.default_buses or {}).get("i2c", {})
    lw = design.lorawan
    onboard_gps = onboard.get("gps_neo6m")
    external_gps = lw.gps if (lw and lw.gps) else None
    onboard_oled = onboard.get("oled_ssd1306")
    ctx = {
        "has_gps": bool(onboard_gps or external_gps),
        "has_axp": "axp192" in onboard,
        "has_dht": bool(lw and lw.dht22),
        "has_oled": bool(onboard_oled or (lw and lw.oled)),
    }
    if ctx["has_axp"]:
        ctx["i2c_sda"] = _pin(i2c.get("sda"))
        ctx["i2c_scl"] = _pin(i2c.get("scl"))
    if onboard_gps:
        # The peripheral's TX is the MCU's RX (and vice-versa).
        ctx["gps_rx"] = _pin(onboard_gps.get("tx"))
        ctx["gps_tx"] = _pin(onboard_gps.get("rx"))
        ctx["gps_baud"] = onboard_gps.get("baud", 9600)
    elif external_gps:
        ctx["gps_rx"] = _pin(external_gps.rx_pin)
        ctx["gps_tx"] = _pin(external_gps.tx_pin)
        ctx["gps_baud"] = external_gps.baud
    if ctx["has_dht"]:
        ctx["dht_pin"] = _pin(lw.dht22.pin)
    if ctx["has_oled"]:
        p = onboard_oled or {}
        ctx["oled_sda"] = _pin(p.get("sda") or i2c.get("sda"))
        ctx["oled_scl"] = _pin(p.get("scl") or i2c.get("scl"))
        ctx["oled_reset"] = _pin(p["reset"]) if p.get("reset") else None
        ctx["oled_vext"] = _pin(p["vext"]) if p.get("vext") else None
        ctx["oled_addr"] = p.get("address", "0x3C")
    return ctx


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
        **_radio_ctx(board.radio),
        **_sensor_ctx(design, board),
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
