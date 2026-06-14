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

    components = list(design.components)

    # Add onboard peripherals implicitly
    onboard = board.onboard_peripherals or {}

    has_gps = False
    has_dht = False
    has_oled = False
    has_axp = False
    for comp in components:
        if comp.library_id == "uart_gps":
            has_gps = True
        elif comp.library_id == "dht":
            has_dht = True
        elif comp.library_id == "ssd1306":
            has_oled = True
        elif comp.library_id == "axp192":
            has_axp = True

    if "gps_neo6m" in onboard or getattr(lw, "gps", None) is not None:
        if not has_gps:
            from wirestudio.model import Component
            gps_conf = getattr(lw, "gps", None)
            params = {}
            if gps_conf:
                params = {"rx_pin": gps_conf.rx_pin, "tx_pin": gps_conf.tx_pin, "baud": gps_conf.baud}
            elif "gps_neo6m" in onboard:
                params = {"rx_pin": onboard["gps_neo6m"].get("tx"), "tx_pin": onboard["gps_neo6m"].get("rx"), "baud": onboard["gps_neo6m"].get("baud", 9600)}
            components.append(Component(id="gps", library_id="uart_gps", label="GPS", params=params))

    if "axp192" in onboard and not has_axp:
        from wirestudio.model import Component
        components.append(Component(id="axp192", library_id="axp192", label="PMIC"))

    if getattr(lw, "dht22", None) is not None and not has_dht:
        from wirestudio.model import Component
        dht_conf = getattr(lw, "dht22", None)
        components.append(Component(id="dht1", library_id="dht", label="DHT", params={"pin": dht_conf.pin, "model": "DHT22"}))

    if "oled_ssd1306" in onboard or getattr(lw, "oled", None) is not None:
        if not has_oled:
            from wirestudio.model import Component
            params = {}
            if "oled_ssd1306" in onboard:
                params = {"address": onboard["oled_ssd1306"].get("address", "0x3C")}
                if onboard["oled_ssd1306"].get("reset"):
                    params["reset_pin"] = onboard["oled_ssd1306"]["reset"]
                if onboard["oled_ssd1306"].get("vext"):
                    params["vext_pin"] = onboard["oled_ssd1306"]["vext"]
            components.append(Component(id="oled", library_id="ssd1306", label="OLED", params=params))
    component_lib_deps = []
    component_requires = set()
    component_globals = []
    component_setup = []
    component_loop = []

    for comp_inst in components:
        try:
            lib_comp = library.component(comp_inst.library_id)
            if lib_comp.lorawan:
                lw_spec = lib_comp.lorawan
                if lw_spec.lib_deps:
                    for dep in lw_spec.lib_deps:
                        if dep not in component_lib_deps:
                            component_lib_deps.append(dep)
                if lw_spec.requires:
                    for req in lw_spec.requires:
                        component_requires.add(req)

                import jinja2
                env = jinja2.Environment()

                pins = {}
                bus = None
                for conn in design.connections:
                    if conn.component_id == comp_inst.id:
                        if conn.target.kind == "gpio":
                            pins[conn.pin_role] = _pin(conn.target.pin)
                        elif conn.target.kind == "bus":
                            for b in design.buses:
                                if b.id == conn.target.bus_id:
                                    bus = {"id": b.id, "sda": _pin(getattr(b, "sda", None)), "scl": _pin(getattr(b, "scl", None)), "rx": _pin(getattr(b, "rx", None)), "tx": _pin(getattr(b, "tx", None))}
                                    break

                pin = pins.get("pin") or list(pins.values())[0] if pins else None

                render_ctx = {"id": comp_inst.id, "label": comp_inst.label, "params": comp_inst.params, "pin": pin, "pins": pins, "bus": bus, "onboard": onboard, "board": board, "i2c_sda": _pin((board.default_buses or {}).get("i2c", {}).get("sda")), "i2c_scl": _pin((board.default_buses or {}).get("i2c", {}).get("scl"))}

                if lw_spec.globals:
                    component_globals.append(env.from_string(lw_spec.globals).render(**render_ctx))
                if lw_spec.setup:
                    component_setup.append(env.from_string(lw_spec.setup).render(**render_ctx))
                if lw_spec.loop:
                    component_loop.append(env.from_string(lw_spec.loop).render(**render_ctx))
        except Exception:
            pass

    # get i2c_sda and i2c_scl for template setup
    i2c = (board.default_buses or {}).get("i2c", {})
    i2c_sda = _pin(i2c.get("sda"))
    i2c_scl = _pin(i2c.get("scl"))

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
