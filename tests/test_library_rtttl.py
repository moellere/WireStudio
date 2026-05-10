"""Tests for the rtttl library entry's chip-family conditional + GND pin."""
from __future__ import annotations

import pytest
import yaml

from wirestudio.agent.tools import _run_add_component, _run_render
from wirestudio.library import default_library


@pytest.fixture
def library():
    return default_library()


def _design(board_id: str) -> dict:
    return {
        "schema_version": "0.1",
        "id": "rtttl-test",
        "name": "RTTTL Test",
        "board": {"library_id": board_id, "mcu": "esp32", "framework": "arduino"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": [],
        "buses": [],
        "connections": [],
    }


def test_rtttl_has_gnd_pin(library):
    """Library entry models the piezo's second terminal as a ground pin so
    add_component seeds a GND -> ground-rail connection automatically."""
    rtttl = library.component("rtttl")
    pin_roles = {p.role for p in rtttl.electrical.pins}
    assert pin_roles == {"OUT", "GND"}
    gnd = next(p for p in rtttl.electrical.pins if p.role == "GND")
    assert gnd.kind == "ground"


def test_rtttl_add_seeds_gnd_to_ground_rail(library):
    """Regression: piezo GND must land on the GND rail, not floating."""
    design = _design("esp32-s3-devkitc-1")
    _run_add_component(design, library, library_id="rtttl")
    gnd_conn = next(
        c for c in design["connections"]
        if c["component_id"].startswith("rtttl_") and c["pin_role"] == "GND"
    )
    assert gnd_conn["target"] == {"kind": "rail", "rail": "GND"}


def test_rtttl_template_picks_ledc_on_esp32(library):
    """ESP32 family boards must default to `ledc` (the only PWM platform
    that works on ESP32) rather than the legacy esp8266_pwm."""
    design = _design("esp32-s3-devkitc-1")
    _run_add_component(design, library, library_id="rtttl")
    result = _run_render(design, library)
    assert result["ok"] is True, result.get("error")
    parsed = yaml.safe_load(result["yaml"])
    output_entries = parsed.get("output", [])
    rtttl_output = next(o for o in output_entries if "rtttl_" in o.get("id", ""))
    assert rtttl_output["platform"] == "ledc"


def test_rtttl_template_picks_esp8266_pwm_on_esp8266(library):
    """ESP8266 boards must default to `esp8266_pwm` -- ledc doesn't exist
    on that chip family."""
    design = _design("wemos-d1-mini")
    design["board"]["mcu"] = "esp8266"
    _run_add_component(design, library, library_id="rtttl")
    result = _run_render(design, library)
    assert result["ok"] is True, result.get("error")
    parsed = yaml.safe_load(result["yaml"])
    output_entries = parsed.get("output", [])
    rtttl_output = next(o for o in output_entries if "rtttl_" in o.get("id", ""))
    assert rtttl_output["platform"] == "esp8266_pwm"


def test_rtttl_template_respects_explicit_param_override(library):
    """If the user explicitly sets `output_platform`, that wins over the
    chip-family default. Lets a user force `ledc` on weird ESP32 forks
    or `esp8266_pwm` on an ESP8266 variant where the chip-family heuristic
    might guess wrong."""
    design = _design("esp32-s3-devkitc-1")
    _run_add_component(
        design, library, library_id="rtttl",
        params={"output_platform": "esp8266_pwm"},
    )
    result = _run_render(design, library)
    assert result["ok"] is True
    parsed = yaml.safe_load(result["yaml"])
    rtttl_output = next(o for o in parsed.get("output", []) if "rtttl_" in o.get("id", ""))
    assert rtttl_output["platform"] == "esp8266_pwm"
