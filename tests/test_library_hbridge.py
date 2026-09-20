"""The `hbridge` template's three expose modes: bare outputs for a control
loop, interlocked forward/reverse switches, and ESPHome's hbridge fan."""
from __future__ import annotations

import pytest

from wirestudio.generate.yaml_gen import render_yaml
from wirestudio.library import default_library
from wirestudio.model import Design


@pytest.fixture
def lib():
    return default_library()


@pytest.mark.parametrize("expose, present, absent", [
    ("none", ["platform: gpio", "id: m_in1"], ["fan:", "switch:"]),
    ("switches", ["interlock:", "name: Motor forward"], ["output:", "fan:"]),
    ("fan", ["platform: ledc", "platform: hbridge", "pin_a: m_in1"], ["switch:"]),
])
def test_hbridge_expose_modes(lib, expose, present, absent):
    design = Design.model_validate({
        "schema_version": "0.1", "id": "t", "name": "t",
        "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32", "framework": "esp-idf"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 2000},
        "components": [{"id": "m", "library_id": "hbridge", "label": "Motor",
                        "params": {"expose": expose}}],
        "buses": [], "requirements": [], "warnings": [],
        "connections": [
            {"component_id": "m", "pin_role": "IN1", "target": {"kind": "gpio", "pin": "GPIO18"}},
            {"component_id": "m", "pin_role": "IN2", "target": {"kind": "gpio", "pin": "GPIO19"}},
        ],
    })
    text = render_yaml(design, lib)
    for needle in present:
        assert needle in text
    for needle in absent:
        assert needle not in text
