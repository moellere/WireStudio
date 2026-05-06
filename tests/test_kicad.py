"""Tests for the KiCad SKiDL schematic generator (0.9).

The generator is pure text-out, so we lean on substring assertions +
`compile()` to verify the emitted script is valid Python. Three concerns:

  1. Mapping plumbing: kicad: blocks on the library entries flow into
     Part(...) calls with the right symbol, footprint, value, and
     pin_map applied to the connection lines.
  2. Fallback: components without a kicad: mapping emit a TODO-tagged
     placeholder rather than crashing.
  3. Net derivation: rails / buses / gpio / expander_pin / component
     targets each render as the right SKiDL expression.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wirestudio.kicad import generate_skidl
from wirestudio.kicad.generator import _py_var
from wirestudio.library import default_library
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"


@pytest.fixture
def lib():
    return default_library()


def _design(name: str) -> Design:
    return Design.model_validate(json.loads((EXAMPLES_DIR / f"{name}.json").read_text()))


# ---------------------------------------------------------------------------
# Compile + structural checks
# ---------------------------------------------------------------------------

def test_emitted_script_compiles(lib):
    """Every bundled example must produce a Python-syntax-valid script."""
    for name in ("garage-motion", "wasserpir", "oled", "bluemotion",
                 "distance-sensor", "rc522", "esp32-audio", "wemosgps",
                 "ttgo-lora32", "multi-temp"):
        script = generate_skidl(_design(name), lib)
        compile(script, f"<{name}>", "exec")  # raises SyntaxError if bad


def test_skidl_imports_appear(lib):
    script = generate_skidl(_design("garage-motion"), lib)
    assert "from skidl import" in script
    assert "Part" in script and "Net" in script
    assert "generate_schematic()" in script


def test_design_id_appears_in_docstring(lib):
    script = generate_skidl(_design("garage-motion"), lib)
    assert "garage-motion-v1" in script.splitlines()[0]


# ---------------------------------------------------------------------------
# Mapping flow
# ---------------------------------------------------------------------------

def test_bme280_maps_vcc_role_to_vdd_pin(lib):
    """The BME280's KiCad symbol uses VDD; our role is VCC. The pin_map
    should have rewritten the connection line to address VDD."""
    script = generate_skidl(_design("garage-motion"), lib)
    assert 'c_bme1["VDD"]' in script
    assert 'c_bme1["VCC"]' not in script


def test_board_renders_as_first_part(lib):
    script = generate_skidl(_design("garage-motion"), lib)
    # The board comment + Part call appear before any component.
    board_idx = script.find('Board: ESP32-DevKitC-V4')
    pir_idx = script.find('pir1 (HC-SR501')
    assert board_idx > 0 and pir_idx > 0 and board_idx < pir_idx


def test_known_part_emits_symbol_and_footprint(lib):
    """ESP32 DevKitC V4 carries a footprint hint. It should make it into
    the Part(...) call verbatim."""
    script = generate_skidl(_design("garage-motion"), lib)
    assert 'Part("MCU_Module", "ESP32-DevKitC-V4"' in script
    assert 'footprint="Module:Espressif_ESP32-DevKitC-V4"' in script


def test_unmapped_component_falls_back_to_placeholder(lib):
    """Construct a synthetic design referencing a fictional library
    entry and verify the placeholder + TODO comment land in the
    output. We monkeypatch the library to inject an unmapped entry
    rather than relying on a real-but-unmapped one (the latter
    drifts as new mappings land)."""
    from copy import deepcopy
    from wirestudio.library import LibraryComponent
    fake = LibraryComponent(
        id="zz_fake_unmapped",
        name="Fake unmapped component",
        category="sensor",
    )
    # Mutate a deep-copied library so the global default isn't touched.
    lib_local = deepcopy(lib)
    lib_local._components["zz_fake_unmapped"] = fake
    design = {
        "schema_version": "0.1",
        "id": "fallback",
        "name": "Fallback test",
        "board": {"library_id": "wemos-d1-mini", "mcu": "esp8266"},
        "fleet": {"device_name": "fallback", "tags": []},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": [
            {"id": "x1", "library_id": "zz_fake_unmapped", "label": "X", "params": {}},
        ],
        "buses": [],
        "connections": [],
        "requirements": [],
        "warnings": [],
    }
    script = generate_skidl(Design.model_validate(design), lib_local)
    assert "TODO: zz_fake_unmapped" in script
    assert 'Part("Connector_Generic", "Conn_01x04"' in script


def test_every_library_entry_has_a_kicad_block(lib):
    """Going-forward guardrail: every component + board ships with a
    `kicad:` mapping. New library entries that miss the block fall
    through to the TODO placeholder, which still works but is sub-
    optimal -- this test surfaces the gap loudly so the author either
    adds a block or explicitly opts out by deleting this assertion."""
    from pathlib import Path
    unmapped_components = [c.id for c in lib.list_components() if c.kicad is None]
    unmapped_boards = [
        p.stem for p in Path(__file__).resolve().parent.parent.glob("library/boards/*.yaml")
        if lib.board(p.stem).kicad is None
    ]
    assert unmapped_components == [], (
        f"Components missing a `kicad:` block: {unmapped_components}. "
        f"Add one referencing the matching kicad-symbols entry, or a "
        f"generic Connector_Generic header with the part name as `value:`."
    )
    assert unmapped_boards == [], (
        f"Boards missing a `kicad:` block: {unmapped_boards}."
    )


# ---------------------------------------------------------------------------
# Net derivation
# ---------------------------------------------------------------------------

def test_rail_targets_become_named_nets(lib):
    script = generate_skidl(_design("garage-motion"), lib)
    assert 'GND = Net("GND")' in script
    assert 'NET_PLUS__5V = Net("+5V")' in script
    assert 'NET_PLUS__3V3 = Net("+3V3")' in script


def test_bus_targets_share_a_single_net(lib):
    """All connections targeting bus_id=i2c0 should resolve to the same
    NET_BUS_i2c0 handle so the schematic's I2C pins land on one net."""
    script = generate_skidl(_design("garage-motion"), lib)
    assert 'NET_BUS_i2c0 = Net("BUS_i2c0")' in script
    # Both BME280's SDA + SCL connections go to that single bus net.
    assert 'c_bme1["SDA"] += NET_BUS_i2c0' in script
    assert 'c_bme1["SCL"] += NET_BUS_i2c0' in script


def test_gpio_targets_become_inline_nets(lib):
    script = generate_skidl(_design("garage-motion"), lib)
    # PIR's OUT pin is wired to GPIO13 in this design.
    assert 'c_pir1["OUT"] += Net("GPIO_GPIO13")' in script


def test_expander_pin_targets_render(lib):
    """awning-control wires several gpio_input/output components through
    an MCP23008 expander; expander_pin targets should render as
    Net("<expander>_GP<n>") expressions."""
    script = generate_skidl(_design("awning-control"), lib)
    assert 'GP' in script
    assert 'Net("mcp23008_hub_GP' in script


def test_component_target_renders_for_ads1115_channel():
    """Synthesize a design with the ads1115 hub + channel split and
    verify the channel's HUB connection turns into a Net pointing at
    the hub instance."""
    lib_local = default_library()
    design = {
        "schema_version": "0.1",
        "id": "ads-test",
        "name": "ADS test",
        "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32"},
        "fleet": {"device_name": "ads-test", "tags": []},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": [
            {"id": "adc1", "library_id": "ads1115", "label": "ADC", "params": {}},
            {"id": "bat",  "library_id": "ads1115_channel", "label": "Battery V",
             "params": {"multiplexer": "A0_GND"}},
        ],
        "buses": [{"id": "i2c0", "type": "i2c", "sda": "GPIO21", "scl": "GPIO22"}],
        "connections": [
            {"component_id": "adc1", "pin_role": "VCC", "target": {"kind": "rail", "rail": "3V3"}},
            {"component_id": "adc1", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "adc1", "pin_role": "SDA", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "adc1", "pin_role": "SCL", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "bat",  "pin_role": "HUB", "target": {"kind": "component", "component_id": "adc1"}},
        ],
        "requirements": [],
        "warnings": [],
    }
    script = generate_skidl(Design.model_validate(design), lib_local)
    # ADS1115's VCC role rewrites to VDD via pin_map.
    assert 'c_adc1["VDD"]' in script
    # Channel's HUB connection becomes a hub-relative net.
    assert 'c_bat["HUB"] += Net("adc1_HUB")' in script


# ---------------------------------------------------------------------------
# Identifier sanitisation
# ---------------------------------------------------------------------------

def test_py_var_handles_hyphens_and_digits():
    """Component ids contain hyphens, dots, even leading digits in some
    designs. The sanitiser replaces non-identifier chars with `_` and
    prefixes a leading digit."""
    assert _py_var("foo-bar") == "foo_bar"
    assert _py_var("3w") == "_3w"
    assert _py_var("foo.bar.baz") == "foo_bar_baz"
    assert _py_var("ads1115_channel") == "ads1115_channel"
