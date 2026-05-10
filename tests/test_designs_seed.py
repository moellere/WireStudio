"""Tests for the connection-seeding helpers used by the MCP add_component tool."""
from __future__ import annotations

import pytest

from wirestudio.agent.tools import _run_add_component, _run_render
from wirestudio.designs.seed import (
    add_component_with_connections,
    default_target_for_pin,
    needed_bus_types,
    prepare_buses,
)
from wirestudio.library import default_library


@pytest.fixture
def library():
    return default_library()


def _empty_design(board_id: str = "esp32-s3-devkitc-1") -> dict:
    return {
        "schema_version": "0.1",
        "id": "seed-test",
        "name": "Seed Test",
        "board": {"library_id": board_id, "mcu": "esp32", "framework": "arduino"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": [],
        "buses": [],
        "connections": [],
    }


# ---------------------------------------------------------------------------
# default_target_for_pin
# ---------------------------------------------------------------------------


def test_power_pin_picks_lowest_compatible_rail():
    rails = [{"name": "5V", "voltage": 5.0}, {"name": "3V3", "voltage": 3.3}]
    target = default_target_for_pin(
        "power", rails=rails, buses=[], vcc_min=3.0, vcc_max=3.6
    )
    assert target == {"kind": "rail", "rail": "3V3"}


def test_power_pin_falls_back_to_3v3_when_constraints_unmet():
    rails = [{"name": "5V", "voltage": 5.0}, {"name": "3V3", "voltage": 3.3}]
    target = default_target_for_pin("power", rails=rails, buses=[])
    # No vcc constraints -> picks the lowest non-zero voltage rail.
    assert target == {"kind": "rail", "rail": "3V3"}


def test_ground_pin_picks_zero_voltage_rail():
    rails = [
        {"name": "5V", "voltage": 5.0},
        {"name": "3V3", "voltage": 3.3},
        {"name": "GND", "voltage": 0},
    ]
    assert default_target_for_pin("ground", rails=rails, buses=[]) == {
        "kind": "rail", "rail": "GND",
    }


def test_i2c_sda_pin_picks_first_matching_bus():
    buses = [{"id": "spi_1", "type": "spi"}, {"id": "i2c_1", "type": "i2c"}]
    assert default_target_for_pin("i2c_sda", rails=[], buses=buses) == {
        "kind": "bus", "bus_id": "i2c_1",
    }


def test_i2c_pin_with_no_bus_yields_empty_bus_id():
    assert default_target_for_pin("i2c_sda", rails=[], buses=[]) == {
        "kind": "bus", "bus_id": "",
    }


def test_digital_in_pin_yields_empty_gpio():
    assert default_target_for_pin("digital_in", rails=[], buses=[]) == {
        "kind": "gpio", "pin": "",
    }


# ---------------------------------------------------------------------------
# needed_bus_types
# ---------------------------------------------------------------------------


def test_needed_bus_types_for_i2c_component(library):
    assert needed_bus_types(library.component("sht3xd")) == {"i2c"}


def test_needed_bus_types_for_gpio_component(library):
    # gpio_input is plain digital, no buses needed.
    assert needed_bus_types(library.component("gpio_input")) == set()


# ---------------------------------------------------------------------------
# prepare_buses
# ---------------------------------------------------------------------------


def test_prepare_buses_adds_i2c_with_board_defaults(library):
    design = _empty_design("esp32-devkitc-v4")
    prepare_buses(design, library.component("sht3xd"), library.board("esp32-devkitc-v4"))
    assert len(design["buses"]) == 1
    bus = design["buses"][0]
    assert bus["type"] == "i2c"
    # ESP32-DevKitC-V4 default I2C is GPIO21/GPIO22.
    assert bus.get("sda") and bus.get("scl")


def test_prepare_buses_idempotent_when_bus_present(library):
    design = _empty_design()
    design["buses"].append({"id": "i2c_existing", "type": "i2c", "sda": "GPIO8", "scl": "GPIO9"})
    prepare_buses(design, library.component("sht3xd"), library.board("esp32-s3-devkitc-1"))
    assert len(design["buses"]) == 1  # didn't add a second one


# ---------------------------------------------------------------------------
# add_component_with_connections
# ---------------------------------------------------------------------------


def test_add_creates_a_connection_per_pin(library):
    design = _empty_design()
    instance_id, _ = add_component_with_connections(
        design, library, library_id="hc-sr501"
    )
    own = [c for c in design["connections"] if c["component_id"] == instance_id]
    pin_roles = {c["pin_role"] for c in own}
    expected = {p.role for p in library.component("hc-sr501").electrical.pins}
    assert pin_roles == expected, f"expected {expected}, got {pin_roles}"


def test_add_seeds_buses_for_i2c_component(library):
    design = _empty_design()
    add_component_with_connections(design, library, library_id="sht3xd")
    bus_types = {b["type"] for b in design["buses"]}
    assert "i2c" in bus_types


def test_add_targets_power_pins_to_compatible_rail(library):
    # HC-SR501 wants 5V; on a board with both 5V and 3V3 rails it should
    # bind to 5V.
    design = _empty_design()
    instance_id, _ = add_component_with_connections(
        design, library, library_id="hc-sr501"
    )
    vcc = next(
        c for c in design["connections"]
        if c["component_id"] == instance_id and c["pin_role"] == "VCC"
    )
    assert vcc["target"]["kind"] == "rail"
    assert vcc["target"]["rail"] == "5V"


# ---------------------------------------------------------------------------
# _run_add_component (the MCP tool wrapper)
# ---------------------------------------------------------------------------


def test_mcp_add_component_seeds_connections(library):
    design = _empty_design()
    result = _run_add_component(design, library, library_id="gpio_input")
    assert result["ok"] is True
    instance_id = result["instance_id"]
    own = [c for c in design["connections"] if c["component_id"] == instance_id]
    assert own, "MCP add_component must seed connections, otherwise the renderer crashes on pins.X"


def test_mcp_add_then_render_works_for_three_realistic_components(library):
    """Regression: user asked Claude to add hc_sr501 + gpio_input + rtttl;
    the MCP tool created components without connections, and render() then
    crashed with `StrictUndefined is not JSON serializable` when the rtttl
    template hit `{{ pins.OUT | tojson }}`."""
    design = _empty_design()
    for lib_id in ("hc-sr501", "gpio_input", "rtttl"):
        result = _run_add_component(design, library, library_id=lib_id)
        assert result["ok"] is True

    rendered = _run_render(design, library)
    assert rendered["ok"] is True, f"render failed: {rendered.get('error')}"
    assert "rtttl" in rendered["yaml"]
    assert "binary_sensor" in rendered["yaml"]
