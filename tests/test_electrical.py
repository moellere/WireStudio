"""Rule-based electrical checks a block declares about itself (#274)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.library import Library, default_library
from wirestudio.library.check import check_component_yaml
from wirestudio.library.electrical import run_checks
from wirestudio.model import Design
from wirestudio.validate import check_electrical

BUNDLED = Path(__file__).resolve().parent.parent / "wirestudio" / "library"
EXAMPLES = Path(__file__).resolve().parent.parent / "wirestudio" / "examples"


@pytest.fixture
def lib():
    return default_library()


def _declared(component):
    pins = {p.role: p.voltage for p in component.electrical.pins}
    return lambda role: pins.get(role)


def _one(component, params, pin_voltage=None):
    results, unresolved = run_checks(component, params, pin_voltage or _declared(component))
    assert not unresolved, unresolved
    assert len(results) == 1
    return results[0]


def test_led_current_uses_the_instance_resistor(lib):
    led = lib.component("led_indicator")
    at_default = _one(led, {})
    assert at_default.ok and "5.9 mA" in at_default.text and "r_led 220" in at_default.text
    dim = _one(led, {"r_led": "1k"})
    assert dim.ok and "1.3 mA" in dim.text
    hot = _one(led, {"r_led": "47"})
    assert not hot.ok and "27.7 mA" in hot.text and "outside 1-12 mA" in hot.text
    dark = _one(led, {"r_led": "10k"})
    assert not dark.ok and "0.1 mA" in dark.text


def test_base_drive_compares_load_against_saturation_and_rating(lib):
    npn = lib.component("npn_low_side_driver")
    assert _one(npn, {}).ok
    big = _one(npn, {"load_ma": 150})
    assert not big.ok and "exceeds what 2.60 mA of base current saturates (78 mA" in big.text
    over = _one(npn, {"load_ma": 250})
    assert not over.ok and "exceeds the 200 mA rating" in over.text
    # A lower base resistor buys more saturation current.
    assert _one(npn, {"load_ma": 150, "r_base": "330"}).ok


def test_gate_drive_checks_enhancement_and_dissipation(lib):
    fet = lib.component("mosfet_low_side_driver")
    assert _one(fet, {}).ok
    warm = _one(fet, {"load_ma": 8000})
    assert not warm.ok and "dissipates 2.24 W (over 1 W" in warm.text
    # Drive the gate from a 1.8 V pin instead: not enhanced.
    weak = _one(fet, {}, lambda role: 1.8)
    assert not weak.ok and "1.8 V is below the 3 V" in weak.text


def test_divider_checks_the_pin_ceiling(lib):
    div = lib.component("voltage_divider")
    at_default = _one(div, {})
    assert at_default.ok and "2.55 V on the pin" in at_default.text and "94 uA" in at_default.text
    high = _one(div, {"sense_v": 20})
    assert not high.ok and "4.25 V on the pin (over the 3.1 V ceiling)" in high.text
    assert _one(div, {"sense_v": 20, "r_top": 220000}).ok


def test_rail_driven_checks_resolve_only_inside_a_design(lib):
    bridge = lib.component("hbridge_mosfet")
    results, unresolved = run_checks(bridge, {}, _declared(bridge))
    assert [r.kind for r in results] == ["base_drive"]
    assert unresolved == ["gate_drive: voltage on VM is not known here"]
    # component_check reports the same split and narrows not_checked.
    report = check_component_yaml((BUNDLED / "components" / "hbridge_mosfet.yaml").read_text(), lib)
    assert report.ok
    assert any(line.startswith("base_drive:") for line in report.verified)
    assert any("not evaluated here, gate_drive" in u for u in report.unverified)
    assert report.not_checked[0].startswith("electrical behaviour beyond the 2 declared checks")

    design = Design.model_validate(json.loads((EXAMPLES / "motor-position.json").read_text()))
    assert check_electrical(design, lib) == []  # VM on 5V: 5 >= 4.5
    raw = json.loads((EXAMPLES / "motor-position.json").read_text())
    for c in raw["connections"]:
        if c["pin_role"] == "VM":
            c["target"] = {"kind": "rail", "rail": "3V3"}
    warnings = check_electrical(Design.model_validate(raw), lib)
    assert [w.code for w in warnings] == ["electrical_gate_drive"]
    assert warnings[0].level == "warn" and "3.3 V is below the 4.5 V" in warnings[0].text


def test_unresolved_in_a_design_is_info_not_warn(lib):
    raw = json.loads((EXAMPLES / "bench-io.json").read_text())
    raw["connections"] = [c for c in raw["connections"]
                          if not (c["component_id"] == "onewire_5v" and c["pin_role"] == "VCC")]
    warnings = check_electrical(Design.model_validate(raw), lib)
    assert [(w.level, w.code) for w in warnings] == [("info", "electrical_unresolved")]
    assert "VCC is not known" in warnings[0].text


def test_a_block_whose_defaults_fail_its_own_rule_is_rejected(lib):
    text = (BUNDLED / "components" / "led_indicator.yaml").read_text().replace('default: "220"', 'default: "47"')
    report = check_component_yaml(text, lib)
    assert not report.ok and any("led_current" in e and "outside" in e for e in report.errors)
    # A rule naming a part the subcircuit lacks is unresolved, not a crash.
    text = (BUNDLED / "components" / "led_indicator.yaml").read_text().replace("resistor: r_led,", "resistor: r_nope,")
    report = check_component_yaml(text, lib)
    assert any("no subcircuit part 'r_nope'" in u for u in report.unverified)
    # A check missing its kind's fields is a schema error.
    text = (BUNDLED / "components" / "led_indicator.yaml").read_text().replace(", max_ma: 12}", "}")
    report = check_component_yaml(text, lib)
    assert any("led_current check needs max_ma" in e for e in report.errors)


def test_every_bundled_block_passes_its_own_rules(lib):
    for path in sorted((BUNDLED / "components").glob("*.yaml")):
        report = check_component_yaml(path.read_text(), lib)
        assert report.ok, (path.stem, report.errors)


def test_validate_endpoint_carries_electrical_warnings(tmp_path):
    client = TestClient(create_app(library=Library(BUNDLED, tmp_path / "user")))
    raw = json.loads((EXAMPLES / "bench-io.json").read_text())
    next(c for c in raw["components"] if c["id"] == "fan")["params"]["load_ma"] = 9000
    body = client.post("/design/validate", json=raw).json()
    codes = [w["code"] for w in body["warnings"]]
    assert "electrical_gate_drive" in codes
    assert body["ok"]  # permissive: a warning, not a block
