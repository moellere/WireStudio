"""`lorawan.gps` / `dht22` / `oled` were sugar for a component, a bus and a
few connections. The 1.0 model drops them; the migrator rewrites a document
that still carries them into the components they stood for, so a design
written either way produces the same firmware, payload and profile name."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from wirestudio.library import default_library
from wirestudio.migrate import CURRENT_SCHEMA_VERSION, _lower_lorawan_sugar, migrate
from wirestudio.model import Design
from wirestudio.targets import get_target
from wirestudio.targets.lorawan.codec import fields_for, generate_codec, profile_name
from wirestudio.targets.lorawan.firmware_gen import generate_firmware


@pytest.fixture
def lib():
    return default_library()


def _raw(board_id: str, *, lorawan: dict | None = None, version: str = "0.3", **extra) -> dict:
    return {
        "schema_version": version, "id": "d", "name": "D", "target": "lorawan",
        "lorawan": lorawan if lorawan is not None else {},
        "board": {"library_id": board_id, "mcu": "esp32"},
        "power": {"supply": "usb", "rail_voltage_v": 3.3},
        **extra,
    }


def _design(board_id: str, **kw) -> Design:
    return Design.model_validate(migrate(_raw(board_id, **kw)).document)


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


def test_the_blocks_become_the_explicit_design():
    result = migrate(_raw("heltec-wifi-lora32-v3", lorawan=SUGAR))
    assert result.applied == ["retire_lorawan_sugar"]
    assert result.to_version == CURRENT_SCHEMA_VERSION == "1.0"
    doc = result.document
    assert {k: doc[k] for k in ("components", "buses", "connections")} == EXPLICIT
    assert doc["lorawan"] == {}


def test_sugar_and_explicit_designs_generate_the_same_artifacts(lib):
    sugar = _design("heltec-wifi-lora32-v3", lorawan=SUGAR)
    explicit = _design("heltec-wifi-lora32-v3", **EXPLICIT)
    assert generate_firmware(sugar, lib) == generate_firmware(explicit, lib)
    assert generate_codec(sugar, lib) == generate_codec(explicit, lib)
    assert profile_name(sugar, lib) == profile_name(explicit, lib)
    assert profile_name(sugar, lib).endswith("-gps-batt-dht")
    names = [f["name"] for f in fields_for(sugar, lib)]
    assert {"lat", "lon", "temp_c", "humidity", "batt_mv"} <= set(names)


def test_migration_leaves_the_input_alone_and_is_idempotent(lib):
    raw = _raw("heltec-wifi-lora32-v3", lorawan=SUGAR)
    doc = migrate(raw).document
    assert raw["lorawan"]["gps"] and "components" not in raw
    assert _lower_lorawan_sugar(doc, lib) is doc
    assert migrate(doc).document is doc


def test_a_0_3_design_without_the_blocks_only_changes_its_version():
    raw = _raw("heltec-wifi-lora32-v3", lorawan={"region": "EU868"})
    assert migrate(raw).document == {**raw, "schema_version": "1.0"}


def test_the_1_0_model_refuses_the_blocks():
    with pytest.raises(ValidationError, match="gps"):
        Design.model_validate(_raw("heltec-wifi-lora32-v3", lorawan=SUGAR, version="1.0"))


def test_a_block_whose_component_is_already_placed_is_dropped(lib):
    design = _design(
        "heltec-wifi-lora32-v3", lorawan={"dht22": {"pin": "GPIO13"}},
        components=[{"id": "env", "library_id": "dht", "label": "Env", "params": {}}],
        connections=[{"component_id": "env", "pin_role": "DATA",
                      "target": {"kind": "gpio", "pin": "GPIO4"}}],
    )
    assert [c.id for c in design.components] == ["env"]
    assert "DHT dht(4, DHT22);" in generate_firmware(design, lib)["src/main.cpp"]


def test_ids_do_not_collide_with_what_the_design_has():
    design = _design(
        "heltec-wifi-lora32-v3", lorawan={"gps": {"rx_pin": "GPIO23", "tx_pin": "GPIO17"}},
        components=[{"id": "gps", "library_id": "gpio_input", "label": "Button", "params": {}}],
        buses=[{"id": "gps_uart", "type": "uart", "rx": "GPIO3", "tx": "GPIO1"}],
    )
    gps = next(c for c in design.components if c.library_id == "uart_gps")
    assert gps.id == "gps2"
    assert {b.id for b in design.buses} == {"gps_uart", "gps_uart2"}


def test_onboard_gps_stays_synthesized_without_sugar(lib):
    """The T-Beam's GPS comes from the board file, not from a block; the
    golden firmware for it does not move."""
    design = _design("ttgo-t-beam")
    assert design.components == []
    assert "GPSSerial.begin(9600, SERIAL_8N1, 34, 12)" in generate_firmware(design, lib)["src/main.cpp"]


def test_oled_disabled_is_no_oled():
    assert _design("heltec-wifi-lora32-v3", lorawan={"oled": {"enabled": False}}).components == []


def test_the_migrated_design_validates_clean(lib):
    assert get_target("lorawan").validate(_design("heltec-wifi-lora32-v3", lorawan=SUGAR), lib) == []
