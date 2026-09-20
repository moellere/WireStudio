"""Checking and creating library components at runtime (#263, phase 5)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.library import Library, default_library
from wirestudio.library.check import check_component_yaml, create_component

BUNDLED = Path(__file__).resolve().parent.parent / "wirestudio" / "library"
HBRIDGE = (BUNDLED / "components" / "hbridge_mosfet.yaml").read_text()

DRAFT = """\
id: led_driver_npn
name: NPN low-side LED driver
category: actuator
use_cases: [led, indicator]
electrical:
  vcc_min: 3.0
  vcc_max: 5.5
  pins:
  - {role: IN, kind: digital_out, voltage: 3.3}
  - {role: VCC, kind: power}
  - {role: GND, kind: ground}
esphome:
  required_components: []
  yaml_template: |
    output:
      - platform: gpio
        pin: {{ pins.IN | tojson }}
        id: {{ id }}_out
kicad:
  symbol_lib: Connector_Generic
  symbol: Conn_01x03
  footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
subcircuit:
  parts:
  - id: q1
    ref_prefix: Q
    kicad: {symbol_lib: Transistor_BJT, symbol: 2N3904, footprint: "Package_TO_SOT_THT:TO-92_Inline", value: 2N3904}
    pins: {C: led_k, B: base, E: GND}
    requires: {family: bjt, polarity: npn, v_min: 10, i_min: 0.05}
  - id: r_base
    ref_prefix: R
    kicad: {symbol_lib: Device, symbol: R, footprint: "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal", value: "1k"}
    pins: {"1": IN, "2": base}
  - id: r_led
    ref_prefix: R
    kicad: {symbol_lib: Device, symbol: R, footprint: "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal", value: "220"}
    pins: {"1": VCC, "2": led_a}
  - id: d1
    ref_prefix: D
    kicad: {symbol_lib: Device, symbol: LED, footprint: "LED_THT:LED_D5.0mm", value: LED}
    pins: {A: led_a, K: led_k}
"""


@pytest.fixture
def lib(tmp_path):
    return Library(BUNDLED, tmp_path / "user")


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(library=Library(BUNDLED, tmp_path / "user")))


def test_every_bundled_component_passes(lib):
    """The bar a draft is held to is one every shipped component clears."""
    for path in sorted((BUNDLED / "components").glob("*.yaml")):
        report = check_component_yaml(path.read_text(), lib)
        assert report.ok, (path.stem, report.errors)
        assert report.exists == "bundled"


def test_draft_passes_and_says_what_it_did_not_check(lib):
    report = check_component_yaml(DRAFT, lib)
    assert report.ok and report.library_id == "led_driver_npn" and report.exists == ""
    assert report.warnings == []
    assert any("simulated" in line for line in report.not_checked)
    # No KiCad libraries in this environment: said, not skipped silently.
    assert any("KiCad symbols not checked" in u for u in report.unverified)


def test_malformed_yaml_and_schema_errors(lib):
    assert "not valid YAML" in check_component_yaml("id: [", lib).errors[0]
    assert "mapping" in check_component_yaml("- a\n- b\n", lib).errors[0]
    report = check_component_yaml("id: x\nname: X\ncategory: c\nbogus: 1\n", lib)
    assert not report.ok and any("bogus" in e for e in report.errors)
    report = check_component_yaml(DRAFT.replace("id: led_driver_npn", "id: LED Driver"), lib)
    assert any("must be lowercase" in e for e in report.errors)


def test_subcircuit_net_sanity(lib):
    dangling = DRAFT.replace("pins: {A: led_a, K: led_k}", "pins: {A: led_a, K: led_kk}")
    report = check_component_yaml(dangling, lib)
    assert report.ok  # a warning, not an error: the reviewer decides
    assert any("'led_kk' is touched only by d1.K" in w for w in report.warnings)
    assert any("'led_k' is touched only by q1.C" in w for w in report.warnings)

    unused = DRAFT.replace("pins: {C: led_k, B: base, E: GND}", "pins: {C: led_k, B: base, E: led_k}")
    report = check_component_yaml(unused, lib)
    assert any("pin role 'GND' is not connected" in w for w in report.warnings)

    twice = DRAFT.replace("- id: r_led", "- id: r_base")
    assert any("declared twice" in e for e in check_component_yaml(twice, lib).errors)

    wrong_family = DRAFT.replace("requires: {family: bjt", "requires: {family: diode")
    report = check_component_yaml(wrong_family, lib)
    assert any("does not fit designator prefix Q" in w for w in report.warnings)


def test_template_is_rendered_against_a_synthetic_design(lib):
    broken = DRAFT.replace("{{ pins.IN | tojson }}", "{{ pins.OUT | tojson }}")
    report = check_component_yaml(broken, lib)
    assert not report.ok
    assert any("does not render" in e for e in report.errors)

    syntax = DRAFT.replace("{{ id }}_out", "{{ id _out")
    report = check_component_yaml(syntax, lib)
    assert any("esphome.yaml_template line" in e for e in report.errors)

    # Bus components render on a synthetic bus of their type.
    bme = (BUNDLED / "components" / "bme280.yaml").read_text()
    assert check_component_yaml(bme, lib).ok


def test_symbol_pins_are_checked_when_libraries_exist(lib, tmp_path, monkeypatch):
    symdir = tmp_path / "symbols"
    symdir.mkdir()
    (symdir / "Transistor_BJT.kicad_sym").write_text(
        '(kicad_symbol_lib (version 20231120) (generator kicad_symbol_editor)'
        ' (symbol "2N3904" (pin passive line (at 0 0 0) (length 2.54) (name "E") (number "1"))'
        ' (pin passive line (at 0 0 0) (length 2.54) (name "B") (number "2"))'
        ' (pin passive line (at 0 0 0) (length 2.54) (name "C") (number "3"))))')
    monkeypatch.setenv("KICAD8_SYMBOL_DIR", str(symdir))
    report = check_component_yaml(DRAFT, lib)
    errors = " | ".join(report.errors)
    # The BJT resolves; the libraries this stub does not carry are named.
    assert "symbol library 'Device' not found" in errors
    assert "2N3904" not in errors

    wrong_pin = DRAFT.replace("pins: {C: led_k, B: base, E: GND}", "pins: {COL: led_k, B: base, E: GND}")
    report = check_component_yaml(wrong_pin, lib)
    assert any("has no pin 'COL'" in e and "B, C, E" in e for e in report.errors)


def test_create_saves_into_the_user_library_only(lib, tmp_path):
    report = create_component(DRAFT, lib)
    assert report.ok and report.saved.endswith("user/components/led_driver_npn.yaml")
    assert lib.component_source("led_driver_npn") == "user"
    assert lib.component("led_driver_npn").subcircuit is not None
    assert "led_driver_npn" in [c.id for c in lib.list_components()]
    # Comments survive: the file is the text, not a model dump.
    assert Path(report.saved).read_text() == DRAFT

    again = create_component(DRAFT, lib)
    assert not again.ok and any("already exists" in e for e in again.errors)
    assert create_component(DRAFT, lib, overwrite=True).ok

    bundled = create_component(HBRIDGE, lib)
    assert not bundled.ok and any("bundled" in e for e in bundled.errors)
    assert not (tmp_path / "user" / "components" / "hbridge_mosfet.yaml").exists()

    broken = create_component(DRAFT.replace("{{ pins.IN | tojson }}", "{{ pins.OUT }}"), lib)
    assert not broken.ok and broken.saved == ""

    assert not create_component(DRAFT, Library(BUNDLED)).ok  # no user dir configured


def test_user_component_flows_into_a_design(lib):
    """The point of the exercise: a created component generates like a
    bundled one -- YAML, and a subcircuit expansion for the fab outputs."""
    from wirestudio.generate.yaml_gen import render_yaml
    from wirestudio.kicad.netlist import placed_parts
    from wirestudio.model import Design

    assert create_component(DRAFT, lib).ok
    design = Design.model_validate({
        "schema_version": "0.1", "id": "t", "name": "t",
        "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32", "framework": "esp-idf"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": [{"id": "led", "library_id": "led_driver_npn", "label": "Status"}],
        "buses": [], "requirements": [], "warnings": [],
        "connections": [
            {"component_id": "led", "pin_role": "IN", "target": {"kind": "gpio", "pin": "GPIO18"}},
        ],
    })
    assert "pin: GPIO18" in render_yaml(design, lib)
    refs = [p.ref for p in placed_parts(design, lib) if p.part_id]
    assert refs == ["Q1", "R1", "R2", "D1"]


def test_default_library_reads_user_dir_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LIBRARY_USER_DIR", str(tmp_path / "u"))
    assert default_library().user_dir == tmp_path / "u"
    monkeypatch.delenv("LIBRARY_USER_DIR")
    assert default_library().user_dir is None


def test_check_and_create_endpoints(client):
    body = client.post("/library/components/check", json={"yaml": DRAFT}).json()
    assert body["ok"] and body["exists"] == "" and body["saved"] == ""

    r = client.post("/library/components", json={"yaml": DRAFT})
    assert r.status_code == 201 and r.json()["saved"]
    assert client.get("/library/components/led_driver_npn").status_code == 200

    r = client.post("/library/components", json={"yaml": DRAFT})
    assert r.status_code == 409
    assert client.post("/library/components", json={"yaml": DRAFT, "overwrite": True}).status_code == 201
    assert client.post("/library/components", json={"yaml": HBRIDGE}).status_code == 409

    r = client.post("/library/components", json={"yaml": "id: [", "overwrite": False})
    assert r.status_code == 422 and r.json()["errors"]
