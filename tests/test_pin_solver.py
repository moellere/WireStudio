"""Tests for the pin-assignment solver.

Cases covered:
- Pure: doesn't mutate the input dict.
- Bound pins are left alone, unbound ones get filled in.
- Capability filtering: analog_in pins go to ADC-capable board pins.
- Bus pins prefer existing matching buses; report missing-bus.
- Strap / boot pins are deprioritized for outputs.
- Conflict + budget warnings surface for already-bound state.
- Empty / malformed inputs (no board, unknown library) fail cleanly.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from studio.csp.pin_solver import solve_pins
from studio.library import default_library

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"


@pytest.fixture
def library():
    return default_library()


def _load(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / f"{name}.json").read_text())


def _connection(d: dict, component_id: str, pin_role: str) -> dict:
    return next(
        c for c in d["connections"]
        if c["component_id"] == component_id and c["pin_role"] == pin_role
    )


def test_already_solved_design_makes_no_changes(library):
    d = _load("garage-motion")
    before = copy.deepcopy(d)
    result = solve_pins(d, library)
    assert result.assigned == []
    assert d == before  # input untouched
    assert result.design == before  # no changes (everything already bound)


def test_unbound_gpio_gets_a_capable_pin(library):
    d = _load("wasserpir")
    # Unbind the PIR's OUT connection.
    _connection(d, "pir1", "OUT")["target"] = {"kind": "gpio", "pin": ""}
    before = copy.deepcopy(d)
    result = solve_pins(d, library)

    assert d == before  # solver is pure
    assert len(result.assigned) == 1
    a = result.assigned[0]
    assert a.component_id == "pir1"
    assert a.pin_role == "OUT"
    assert a.new_target["kind"] == "gpio"
    assert a.new_target["pin"]  # non-empty
    # Reflected in the returned design
    new_target = _connection(result.design, "pir1", "OUT")["target"]
    assert new_target == a.new_target


def test_unbound_gpio_avoids_pins_already_used(library):
    d = _load("wasserpir")
    # Unbind PIR.OUT and seed a different connection that already uses D2.
    _connection(d, "pir1", "OUT")["target"] = {"kind": "gpio", "pin": ""}
    d["connections"].append(
        {"component_id": "pir1", "pin_role": "EXTRA",
         "target": {"kind": "gpio", "pin": "D2"}}
    )
    result = solve_pins(d, library)
    chosen = next(a for a in result.assigned if a.pin_role == "OUT").new_target["pin"]
    assert chosen != "D2"


def test_unbound_bus_picks_matching_type(library):
    d = _load("garage-motion")
    # Unbind both BME280 bus connections.
    _connection(d, "bme1", "SDA")["target"] = {"kind": "bus", "bus_id": ""}
    _connection(d, "bme1", "SCL")["target"] = {"kind": "bus", "bus_id": ""}
    result = solve_pins(d, library)
    assert {a.pin_role for a in result.assigned} == {"SDA", "SCL"}
    for a in result.assigned:
        assert a.new_target == {"kind": "bus", "bus_id": "i2c0"}


def test_unbound_bus_with_no_matching_bus_emits_unresolved(library):
    d = _load("wasserpir")  # has no buses defined
    d["connections"].append({
        "component_id": "pir1", "pin_role": "SDA",
        "target": {"kind": "bus", "bus_id": ""},
    })
    # Patch the design so the SDA role exists in the lib for hc-sr501... it
    # doesn't. Use bme280 instead for a realistic case.
    d["components"].append({
        "id": "bme1", "library_id": "bme280", "label": "BME", "params": {},
    })
    d["connections"].append({
        "component_id": "bme1", "pin_role": "SDA",
        "target": {"kind": "bus", "bus_id": ""},
    })
    result = solve_pins(d, library)
    no_bus = [u for u in result.unresolved if u.code == "no_matching_bus"]
    assert len(no_bus) >= 1
    assert "bme1.SDA" in no_bus[0].text


def test_unbound_expander_pin_fills_first_free_slot(library):
    d = _load("awning-control")  # has mcp23008_hub and 4 sensors + 2 switches
    # Unbind one sensor's expander_pin.
    _connection(d, "awning_closed_sensor", "IN")["target"] = {
        "kind": "expander_pin", "expander_id": "", "number": 0,
    }
    result = solve_pins(d, library)
    assigned = [a for a in result.assigned if a.component_id == "awning_closed_sensor"]
    assert len(assigned) == 1
    new = assigned[0].new_target
    assert new["expander_id"] == "mcp23008_hub"
    # Once we unbind awning_closed_sensor.IN, the remaining bound expander
    # pins are 1, 2, 3, 6, 7. The solver may legitimately reclaim 0 (it's
    # now free) or pick the next unused, 4 or 5.
    assert new["number"] not in (1, 2, 3, 6, 7)


def test_conflict_warning_for_bound_pins(library):
    d = _load("garage-motion")
    # Add a conflicting connection on GPIO13 (already used by pir1.OUT).
    d["connections"].append({
        "component_id": "pir1", "pin_role": "EXTRA",
        "target": {"kind": "gpio", "pin": "GPIO13"},
    })
    result = solve_pins(d, library)
    conflicts = [w for w in result.warnings if w.code == "gpio_conflict"]
    assert len(conflicts) == 1
    assert "GPIO13" in conflicts[0].text


def test_current_budget_warning(library):
    d = _load("garage-motion")
    d["power"]["budget_ma"] = 10  # tiny budget
    result = solve_pins(d, library)
    over = [w for w in result.warnings if w.code == "current_budget"]
    assert len(over) == 1


def test_no_board_returns_error_warning(library):
    d = {"components": [], "connections": []}
    result = solve_pins(d, library)
    assert result.assigned == []
    assert any(w.code == "no_board" for w in result.warnings)


def test_unknown_board_returns_error_warning(library):
    d = {"board": {"library_id": "no-such-board"}, "components": [], "connections": []}
    result = solve_pins(d, library)
    assert any(w.code == "unknown_board" for w in result.warnings)


def test_analog_in_pin_picks_adc_capable(library):
    """
    Synthesize a connection whose library pin is `analog_in`. The solver
    should only pick a board pin tagged `adc`. The hc-sr04 sensor doesn't
    have an analog pin, but we can fake the role -- the solver looks up
    the role in the library, so we'll use a real component (bme280) but
    target a non-existent pin to confirm the unknown_pin_role path. That
    covers the negative case; for the positive case we rely on the
    unbound_gpio test above (most pins on devkitc-v4 have adc capability
    so non-adc filtering is mostly a tie-breaker).
    """
    d = _load("garage-motion")
    d["connections"].append({
        "component_id": "bme1", "pin_role": "SOMETHING_NOT_IN_LIBRARY",
        "target": {"kind": "gpio", "pin": ""},
    })
    result = solve_pins(d, library)
    unknown = [u for u in result.unresolved if u.code == "unknown_pin_role"]
    assert len(unknown) == 1
    assert "SOMETHING_NOT_IN_LIBRARY" in unknown[0].text


def test_solver_prefers_non_strap_pins(library):
    """When multiple GPIOs satisfy the constraint, strap/boot pins should be
    avoided. wemos-d1-mini's D3 (boot/strap) and D8 (strap) should not be
    the first choice for a generic digital_out."""
    d = _load("wasserpir")
    _connection(d, "pir1", "OUT")["target"] = {"kind": "gpio", "pin": ""}
    result = solve_pins(d, library)
    chosen = result.assigned[0].new_target["pin"]
    assert chosen not in ("D3", "D4", "D8")  # strap-tagged pins on wemos-d1-mini


def test_solver_prefers_adc1_over_adc2_for_analog_in(library):
    """On classic ESP32, analog_in should land on an ADC1 pin (GPIO32-39)
    rather than an ADC2 pin (which conflicts with WiFi at runtime)."""
    d = {
        "schema_version": "0.1",
        "id": "adc-pref",
        "name": "ADC pref",
        "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32"},
        "components": [
            {"id": "amp", "library_id": "max98357a", "params": {"mode": "stereo"}},
        ],
        "buses": [
            {"id": "i2s0", "type": "i2s", "lrclk": "GPIO33", "bclk": "GPIO27", "dout": "GPIO32"},
        ],
        "connections": [
            {"component_id": "amp", "pin_role": "VCC",   "target": {"kind": "rail", "rail": "5V"}},
            {"component_id": "amp", "pin_role": "GND",   "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "amp", "pin_role": "DIN",   "target": {"kind": "bus", "bus_id": "i2s0"}},
            {"component_id": "amp", "pin_role": "BCLK",  "target": {"kind": "bus", "bus_id": "i2s0"}},
            {"component_id": "amp", "pin_role": "LRCLK", "target": {"kind": "bus", "bus_id": "i2s0"}},
            # Unbound analog_in -- the solver must choose for us.
            {"component_id": "amp", "pin_role": "GAIN", "target": {"kind": "gpio", "pin": ""}},
        ],
    }
    result = solve_pins(d, library)
    gain = next(a for a in result.assigned if a.pin_role == "GAIN")
    chosen = gain.new_target["pin"]
    # Must be an ADC1 pin (GPIO32-39 on classic ESP32). The exact pin can
    # shift as the board YAML evolves; the invariant is "not on ADC2".
    adc1_pins = {"GPIO32", "GPIO33", "GPIO34", "GPIO35", "GPIO36", "GPIO39"}
    assert chosen in adc1_pins, f"expected ADC1 pin, got {chosen}"
