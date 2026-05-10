"""Tests for `add_bus` board-defaults behavior."""
from __future__ import annotations

import pytest

from wirestudio.agent.tools import _run_add_bus
from wirestudio.library import default_library


@pytest.fixture
def library():
    return default_library()


def _design(board_id: str) -> dict:
    return {
        "schema_version": "0.1",
        "id": "bus-test",
        "name": "Bus Test",
        "board": {"library_id": board_id, "mcu": "esp32", "framework": "arduino"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": [],
        "buses": [],
        "connections": [],
    }


def test_add_bus_fills_i2c_defaults_for_esp32_s3(library):
    """Regression: Claude calls add_bus(id='i2c0', type='i2c') without
    sda/scl. The previous behavior stored a bus with null pins, which
    ESPHome refuses to compile. With board-defaults applied, the bus
    picks up GPIO8/GPIO9 from the board's `default_buses.i2c` block."""
    design = _design("esp32-s3-devkitc-1")
    result = _run_add_bus(design, library, id="i2c0", type="i2c")
    assert result["ok"] is True
    assert "sda" in result.get("board_defaults_applied", [])
    assert "scl" in result.get("board_defaults_applied", [])

    bus = design["buses"][0]
    assert bus["id"] == "i2c0"
    assert bus["type"] == "i2c"
    assert bus["sda"] == "GPIO8"
    assert bus["scl"] == "GPIO9"


def test_add_bus_fills_spi_defaults(library):
    design = _design("esp32-s3-devkitc-1")
    result = _run_add_bus(design, library, id="spi0", type="spi")
    assert result["ok"] is True
    bus = design["buses"][0]
    assert bus["clk"] == "GPIO12"
    assert bus["miso"] == "GPIO13"
    assert bus["mosi"] == "GPIO11"


def test_user_supplied_fields_override_defaults(library):
    design = _design("esp32-s3-devkitc-1")
    result = _run_add_bus(design, library, id="i2c0", type="i2c", sda="GPIO5")
    assert result["ok"] is True
    bus = design["buses"][0]
    assert bus["sda"] == "GPIO5"          # user value wins
    assert bus["scl"] == "GPIO9"          # filled from board defaults
    # scl was missing from caller -> appears in the applied list, sda doesn't.
    assert "scl" in result.get("board_defaults_applied", [])
    assert "sda" not in result.get("board_defaults_applied", [])


def test_add_bus_with_no_board_defaults_for_type_is_noop(library):
    """uart isn't in default_buses for ESP32-S3 -- the bus should still
    be created, just without auto-filled pins. ESPHome won't compile
    until the user provides rx/tx, but the tool itself doesn't fail."""
    design = _design("esp32-s3-devkitc-1")
    result = _run_add_bus(design, library, id="uart0", type="uart", baud_rate=115200)
    assert result["ok"] is True
    bus = design["buses"][0]
    assert bus["baud_rate"] == 115200
    assert "rx" not in bus
    assert "board_defaults_applied" not in result


def test_add_bus_with_unknown_board_doesnt_crash(library):
    design = _design("esp32-s3-devkitc-1")
    design["board"]["library_id"] = "not-a-real-board"
    # The tool must not raise -- the user can fix the board later. The
    # bus gets created with exactly what was provided.
    result = _run_add_bus(design, library, id="i2c0", type="i2c", sda="GPIO1", scl="GPIO2")
    assert result["ok"] is True
    bus = design["buses"][0]
    assert bus["sda"] == "GPIO1"
    assert bus["scl"] == "GPIO2"
