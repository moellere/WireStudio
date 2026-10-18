"""`lorawan.gps` / `dht22` / `oled` are sugar for a component, a bus and a
few connections. Lowering them is what every reader of a standalone design
does first, so a design written either way produces the same firmware,
payload and profile name."""
from __future__ import annotations

import pytest

from wirestudio.library import default_library
from wirestudio.model import Design
from wirestudio.targets import get_target
from wirestudio.targets.lorawan.codec import fields_for, generate_codec, profile_name
from wirestudio.targets.lorawan.firmware_gen import generate_firmware
from wirestudio.targets.lorawan.lower import lower_lorawan_sugar, sugar_in_use


@pytest.fixture
def lib():
    return default_library()


def _design(board_id: str, *, lorawan: dict | None = None, **extra) -> Design:
    return Design.model_validate({
        "schema_version": "0.1", "id": "d", "name": "D", "target": "lorawan",
        "lorawan": lorawan if lorawan is not None else {},
        "board": {"library_id": board_id, "mcu": "esp32"},
        "power": {"supply": "usb", "rail_voltage_v": 3.3},
        **extra,
    })


SUGAR = {"gps": {"rx_pin": "GPIO23", "tx_pin": "GPIO17"}, "dht22": {"pin": "GPIO13"}, "oled": {}}

EXPLICIT = {
    "components": [
        {"id": "gps", "library_id": "uart_gps", "label": "GPS", "params": {}},
        {"id": "dht1", "library_id": "dht", "label": "DHT", "params": {"model": "DHT22"}},
        {"id": "oled", "library_id": "ssd1306", "label": "OLED",
         "params": {"address": "0x3C", "vext_pin": "GPIO36"}},
    ],
    "buses": [
        {"id": "gps_uart", "type": "uart", "rx": "GPIO23", "tx": "GPIO17", "baud_rate": 9600},
        {"id": "i2c0", "type": "i2c", "sda": "GPIO17", "scl": "GPIO18"},
    ],
    "connections": [
        {"component_id": "gps", "pin_role": "VCC", "target": {"kind": "rail", "rail": "3V3"}},
        {"component_id": "gps", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
        {"component_id": "gps", "pin_role": "TX", "target": {"kind": "bus", "bus_id": "gps_uart"}},
        {"component_id": "gps", "pin_role": "RX", "target": {"kind": "bus", "bus_id": "gps_uart"}},
        {"component_id": "dht1", "pin_role": "VCC", "target": {"kind": "rail", "rail": "3V3"}},
        {"component_id": "dht1", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
        {"component_id": "dht1", "pin_role": "DATA", "target": {"kind": "gpio", "pin": "GPIO13"}},
        {"component_id": "oled", "pin_role": "VCC", "target": {"kind": "rail", "rail": "3V3"}},
        {"component_id": "oled", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
        {"component_id": "oled", "pin_role": "SDA", "target": {"kind": "bus", "bus_id": "i2c0"}},
        {"component_id": "oled", "pin_role": "SCL", "target": {"kind": "bus", "bus_id": "i2c0"}},
        {"component_id": "oled", "pin_role": "RESET", "target": {"kind": "gpio", "pin": "GPIO21"}},
    ],
}


def test_lowering_is_the_explicit_design(lib):
    lowered = lower_lorawan_sugar(_design("heltec-wifi-lora32-v3", lorawan=SUGAR), lib)
    explicit = _design("heltec-wifi-lora32-v3", **EXPLICIT)
    dump = lambda d: d.model_dump(mode="json", exclude={"lorawan"})  # noqa: E731
    assert dump(lowered) == dump(explicit)
    assert sugar_in_use(lowered) == []


def test_sugar_and_explicit_designs_generate_the_same_artifacts(lib):
    sugar = _design("heltec-wifi-lora32-v3", lorawan=SUGAR)
    explicit = _design("heltec-wifi-lora32-v3", **EXPLICIT)
    assert generate_firmware(sugar, lib) == generate_firmware(explicit, lib)
    assert generate_codec(sugar, lib) == generate_codec(explicit, lib)
    assert profile_name(sugar, lib) == profile_name(explicit, lib)
    assert profile_name(sugar, lib).endswith("-gps-batt-dht")
    names = [f["name"] for f in fields_for(sugar, lib)]
    assert {"lat", "lon", "temp_c", "humidity", "batt_mv"} <= set(names)


def test_lowering_leaves_the_input_alone_and_is_idempotent(lib):
    design = _design("heltec-wifi-lora32-v3", lorawan=SUGAR)
    lowered = lower_lorawan_sugar(design, lib)
    assert design.lorawan.gps is not None and design.components == []
    assert lower_lorawan_sugar(lowered, lib) is lowered
    assert lower_lorawan_sugar(_design("heltec-wifi-lora32-v3"), lib) is not lowered


def test_a_block_whose_component_is_already_placed_is_dropped(lib):
    design = _design(
        "heltec-wifi-lora32-v3", lorawan={"dht22": {"pin": "GPIO13"}},
        components=[{"id": "env", "library_id": "dht", "label": "Env", "params": {}}],
        connections=[{"component_id": "env", "pin_role": "DATA",
                      "target": {"kind": "gpio", "pin": "GPIO4"}}],
    )
    lowered = lower_lorawan_sugar(design, lib)
    assert [c.id for c in lowered.components] == ["env"]
    assert lowered.lorawan.dht22 is None
    assert "DHT dht(4, DHT22);" in generate_firmware(design, lib)["src/main.cpp"]


def test_ids_do_not_collide_with_what_the_design_has(lib):
    design = _design(
        "heltec-wifi-lora32-v3", lorawan={"gps": {"rx_pin": "GPIO23", "tx_pin": "GPIO17"}},
        components=[{"id": "gps", "library_id": "gpio_input", "label": "Button", "params": {}}],
        buses=[{"id": "gps_uart", "type": "uart", "rx": "GPIO3", "tx": "GPIO1"}],
    )
    lowered = lower_lorawan_sugar(design, lib)
    gps = next(c for c in lowered.components if c.library_id == "uart_gps")
    assert gps.id == "gps2"
    assert {b.id for b in lowered.buses} == {"gps_uart", "gps_uart2"}


def test_onboard_gps_stays_synthesized_without_sugar(lib):
    """The T-Beam's GPS comes from the board file, not from a block; the
    golden firmware for it does not move."""
    design = _design("ttgo-t-beam")
    assert lower_lorawan_sugar(design, lib) is design
    assert "GPSSerial.begin(9600, SERIAL_8N1, 34, 12)" in generate_firmware(design, lib)["src/main.cpp"]


def test_oled_disabled_is_no_oled(lib):
    design = _design("heltec-wifi-lora32-v3", lorawan={"oled": {"enabled": False}})
    assert lower_lorawan_sugar(design, lib).components == []


def test_validate_names_each_lowered_block(lib):
    warnings = get_target("lorawan").validate(_design("heltec-wifi-lora32-v3", lorawan=SUGAR), lib)
    lowered = [w for w in warnings if w.code == "lorawan_sugar_lowered"]
    assert [w.level for w in lowered] == ["info"] * 3
    assert all(f"lorawan.{f}" in w.text for f, w in zip(("gps", "dht22", "oled"), lowered))
    assert get_target("lorawan").validate(_design("heltec-wifi-lora32-v3", **EXPLICIT), lib) == []


def test_console_uart_check_reads_the_bus_either_way(lib):
    on_console = {"gps": {"rx_pin": "GPIO3", "tx_pin": "GPIO1"}}
    codes = {w.code for w in get_target("lorawan").validate(
        _design("heltec-wifi-lora32-v2", lorawan=on_console), lib)}
    assert "lorawan_gps_on_console_uart" in codes
    explicit = _design(
        "heltec-wifi-lora32-v2",
        components=[{"id": "gnss", "library_id": "uart_gps", "label": "GNSS", "params": {}}],
        buses=[{"id": "u", "type": "uart", "rx": "GPIO3", "tx": "GPIO1"}],
        connections=[{"component_id": "gnss", "pin_role": "TX", "target": {"kind": "bus", "bus_id": "u"}}],
    )
    assert "lorawan_gps_on_console_uart" in {w.code for w in get_target("lorawan").validate(explicit, lib)}
