"""Tests for onboard-peripheral seeding (wirestudio.seed)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from wirestudio.agent.session import FileSessionStore
from wirestudio.api.app import create_app
from wirestudio.generate.yaml_gen import render_yaml
from wirestudio.library import default_library
from wirestudio.model import Design
from wirestudio.seed import seed_onboard_components


@pytest.fixture
def lib():
    return default_library()


def _full_design(board_id: str, frag: dict) -> dict:
    return {
        "schema_version": "0.1", "id": "seed-test", "name": "Seed test",
        "board": {"library_id": board_id, "mcu": "esp32", "framework": "arduino"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "requirements": [], "components": frag["components"], "buses": frag["buses"],
        "connections": frag["connections"], "passives": [], "warnings": [],
        "esphome_extras": {"logger": {}},
        "fleet": {"device_name": "seed-test", "tags": [], "secrets_ref": {
            "wifi_ssid": "!secret wifi_ssid", "wifi_password": "!secret wifi_password",
            "api_key": "!secret api_key"}},
    }


def test_atoms3_seeds_display_button_imu(lib):
    frag = seed_onboard_components(lib.board("m5stack-atoms3"), lib)
    by_id = {c["id"]: c["library_id"] for c in frag["components"]}
    assert by_id == {
        "onboard_display": "st7789",
        "onboard_button": "gpio_input",
        "onboard_imu": "mpu6886",
    }
    # The display is SPI, the IMU is I2C -> both default buses materialise.
    assert {b["type"] for b in frag["buses"]} == {"spi", "i2c"}
    assert frag["warnings"] == []


def test_atoms3_display_wired_to_onboard_pins(lib):
    frag = seed_onboard_components(lib.board("m5stack-atoms3"), lib)
    disp = [c for c in frag["connections"] if c["component_id"] == "onboard_display"]
    cs = next(c for c in disp if c["pin_role"] == "CS")
    assert cs["target"] == {"kind": "gpio", "pin": "GPIO15"}
    # SCK/MOSI land on the shared SPI bus, not raw pins.
    sck = next(c for c in disp if c["pin_role"] == "SCK")
    assert sck["target"]["kind"] == "bus"


def test_seeded_atoms3_renders_valid_yaml(lib):
    """The whole point: the auto-placed parts produce a design that
    renders. (esphome-config gate proves it validates upstream too.)"""
    frag = seed_onboard_components(lib.board("m5stack-atoms3"), lib)
    design = Design.model_validate(_full_design("m5stack-atoms3", frag))
    yaml = render_yaml(design, lib)
    assert "platform: st7789v" in yaml
    assert "platform: mpu6886" in yaml
    assert "platform: gpio" in yaml  # the button binary_sensor


def test_unmapped_peripherals_become_warnings(lib):
    # Atom Echo: button maps; led_sk6812 + echo_i2s have no handler yet.
    frag = seed_onboard_components(lib.board("m5stack-atom-echo"), lib)
    assert [c["library_id"] for c in frag["components"]] == ["gpio_input"]
    codes = {w["code"] for w in frag["warnings"]}
    assert codes == {"onboard_unmapped"}
    assert len(frag["warnings"]) == 2  # led_sk6812, echo_i2s


def test_board_without_onboard_peripherals_seeds_nothing(lib):
    frag = seed_onboard_components(lib.board("esp32-devkitc-v4"), lib)
    assert frag == {"components": [], "buses": [], "connections": [], "warnings": []}


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path) -> TestClient:
    return TestClient(create_app(sessions=FileSessionStore(root=tmp_path)))


def test_seed_onboard_endpoint(client):
    base = {
        "schema_version": "0.1", "id": "x", "name": "x",
        "board": {"library_id": "m5stack-atoms3", "mcu": "esp32", "framework": "arduino"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0},
        "components": [], "buses": [], "connections": [], "warnings": [],
    }
    r = client.post("/design/seed_onboard", json=base)
    assert r.status_code == 200
    out = r.json()
    assert {c["library_id"] for c in out["components"]} == {"st7789", "gpio_input", "mpu6886"}


def test_seed_onboard_endpoint_in_openapi(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/design/seed_onboard" in paths
