"""The WLED target: `cfg.json`'s hardware section from a solved design,
the runtime tier a stock release image reads at boot. Regenerate a
golden with

    python -m wirestudio.targets.wled wirestudio/examples/<stem>.json \\
        > tests/golden/<stem>.wled.json
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.library import default_library
from wirestudio.model import Design
from wirestudio.targets import get_target
from wirestudio.targets.wled import build_cfg, main

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "wirestudio" / "examples"
GOLDEN = REPO_ROOT / "tests" / "golden"
PINNED = ["atom-matrix", "motion-turns-on-light", "flow-meter"]


def _raw(stem: str) -> dict:
    return json.loads((EXAMPLES / f"{stem}.json").read_text())


def _design(stem: str) -> Design:
    return Design.model_validate(_raw(stem))


@pytest.fixture(scope="module")
def lib():
    return default_library()


@pytest.mark.parametrize("stem", PINNED)
def test_examples_match_their_goldens(lib, stem):
    cfg, _ = build_cfg(_design(stem), lib)
    assert json.dumps(cfg, indent=2) + "\n" == (GOLDEN / f"{stem}.wled.json").read_text()


def test_atom_matrix_is_one_rmt_output_and_a_button(lib):
    cfg, warnings = build_cfg(_design("atom-matrix"), lib)
    hw = cfg["hw"]
    [out] = hw["led"]["ins"]
    assert out["type"] == 30 and out["pin"] == [27] and out["len"] == 25 and out["start"] == 0  # SK6812
    assert hw["led"]["total"] == 25
    [btn] = hw["btn"]["ins"]
    assert btn["type"] == 2 and btn["pin"] == [39]
    assert not any("no WLED mapping" in w for w in warnings)


def test_d1_mini_strip_and_pir_resolve_d_labels(lib):
    cfg, _ = build_cfg(_design("motion-turns-on-light"), lib)
    hw = cfg["hw"]
    [out] = hw["led"]["ins"]
    assert out["pin"] == [5]          # D1
    [btn] = hw["btn"]["ins"]
    assert btn["type"] == 5           # PIR sensor
    assert btn["pin"] == [4]          # D2


def test_apa102_is_a_two_wire_output(lib):
    cfg, _ = build_cfg(_design("flow-meter"), lib)
    out = next(o for o in cfg["hw"]["led"]["ins"] if o["type"] == 51)
    assert len(out["pin"]) == 2
    assert out["order"] == 4          # BGR, the apa102 default


def test_chipset_and_order_params_select_the_bus_type(lib):
    raw = _raw("motion-turns-on-light")
    strip = next(c for c in raw["components"] if c["library_id"] == "ws2812b")
    strip["params"] = {**strip.get("params", {}), "variant": "SK6812", "type": "GRBW", "num_leds": 30}
    cfg, warnings = build_cfg(Design.model_validate(raw), lib)
    [out] = cfg["hw"]["led"]["ins"]
    assert out["type"] == 30 and out["order"] == 0 and out["len"] == 30
    assert warnings == []

    strip["params"]["variant"] = "TM1814"
    strip["params"]["type"] = "XYZ"
    cfg, warnings = build_cfg(Design.model_validate(raw), lib)
    assert cfg["hw"]["led"]["ins"][0]["type"] == 31
    assert any("colour order 'XYZ'" in w for w in warnings)


def test_outputs_chain_their_start_index_and_relay_and_ir_are_single(lib):
    raw = _raw("usbc-led-strip")
    raw["components"] += [
        {"id": "strip2", "library_id": "ws2812b", "label": "S2", "params": {"num_leds": 8}},
        {"id": "r1", "library_id": "gpio_output", "label": "R1", "params": {}},
        {"id": "r2", "library_id": "gpio_output", "label": "R2", "params": {}},
        {"id": "ir", "library_id": "remote_receiver", "label": "IR", "params": {}},
    ]
    raw["connections"] += [
        {"component_id": "strip2", "pin_role": "DIN", "target": {"kind": "gpio", "pin": "GPIO16"}},
        {"component_id": "r1", "pin_role": "OUT", "target": {"kind": "gpio", "pin": "GPIO25"}},
        {"component_id": "r2", "pin_role": "OUT", "target": {"kind": "gpio", "pin": "GPIO26"}},
        {"component_id": "ir", "pin_role": "OUT", "target": {"kind": "gpio", "pin": "GPIO4"}},
    ]
    cfg, warnings = build_cfg(Design.model_validate(raw), lib)
    hw = cfg["hw"]
    first, second = hw["led"]["ins"]
    assert second["start"] == first["len"] and hw["led"]["total"] == first["len"] + 8
    assert hw["relay"] == {"pin": 25, "rev": False, "odrain": False}
    assert hw["ir"] == {"pin": 4, "type": 0, "sel": True}
    assert any("r2" in w and "multi_relay" in w for w in warnings)
    assert any("remote layout" in w for w in warnings)


def test_unwired_and_unmapped_parts_warn(lib):
    raw = _raw("usbc-led-strip")
    raw["components"].append({"id": "env", "library_id": "bme280", "label": "Env", "params": {}})
    raw["components"].append({"id": "loose", "library_id": "gpio_input", "label": "B", "params": {}})
    cfg, warnings = build_cfg(Design.model_validate(raw), lib)
    assert any("env (bme280): no WLED mapping" in w for w in warnings)
    assert any("loose.IN: not wired" in w for w in warnings)
    assert cfg["hw"]["btn"]["ins"] == []


def test_bus_pins_ride_the_if_section(lib):
    raw = _raw("usbc-led-strip")
    raw["buses"].append({"id": "i2c0", "type": "i2c", "sda": "GPIO21", "scl": "GPIO22"})
    cfg, _ = build_cfg(Design.model_validate(raw), lib)
    assert cfg["hw"]["if"]["i2c-pin"] == [21, 22]


def test_a_chip_without_a_release_image_is_refused(lib):
    raw = _raw("c6-supermini")
    with pytest.raises(ValueError, match="esp32c6"):
        build_cfg(Design.model_validate(raw), lib)


def test_target_registry_boards_components_and_validate(lib):
    target = get_target("wled")
    assert "m5stack-atom-matrix" in target.board_ids(lib)
    assert not any("c6" in b for b in target.board_ids(lib))
    assert set(target.component_ids(lib)) == {
        "ws2812b", "apa102", "esp32_rmt_led_strip", "gpio_input", "hc-sr501",
        "rcwl-0516", "remote_receiver", "gpio_output",
    }
    files = target.generate(_design("atom-matrix"), lib)
    assert json.loads(files["cfg.json"])["hw"]["led"]["total"] == 25
    assert all(w.code == "wled_unmapped" for w in target.validate(_design("atom-matrix"), lib))


def test_cfg_endpoint_and_cli(capsys):
    client = TestClient(create_app())
    r = client.post("/wled/cfg", json=_raw("atom-matrix"))
    assert r.status_code == 200
    assert r.json()["cfg"]["hw"]["led"]["ins"][0]["pin"] == [27]
    assert client.post("/wled/cfg", json=_raw("c6-supermini")).status_code == 422

    assert main([str(EXAMPLES / "atom-matrix.json")]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["hw"]["led"]["total"] == 25
