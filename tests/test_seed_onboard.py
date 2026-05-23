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


def test_atom_echo_seeds_standard_i2s_mic(lib):
    # Atom Echo: the echo_i2s mic maps to a standard (non-PDM) I2S mic
    # with BCLK wired; LED + button map too, leaving no skips.
    frag = seed_onboard_components(lib.board("m5stack-atom-echo"), lib)
    assert {c["library_id"] for c in frag["components"]} == {
        "esp32_rmt_led_strip", "gpio_input", "i2s_microphone"}
    assert frag["warnings"] == []
    mic = next(c for c in frag["components"] if c["library_id"] == "i2s_microphone")
    assert mic["params"]["pdm"] is False
    roles = {c["pin_role"] for c in frag["connections"] if c["component_id"] == "onboard_mic"}
    assert roles == {"WS", "BCLK", "DIN"}


def test_atomu_seeds_ir_and_pdm_mic(lib):
    frag = seed_onboard_components(lib.board("m5stack-atomu"), lib)
    libs = {c["library_id"] for c in frag["components"]}
    assert {"remote_transmitter", "i2s_microphone"} <= libs
    mic = next(c for c in frag["components"] if c["library_id"] == "i2s_microphone")
    assert mic["params"]["pdm"] is True  # AtomU SPM1423 is a PDM mic
    # PDM has no BCLK -- only WS (clock) + DIN (data).
    roles = {c["pin_role"] for c in frag["connections"] if c["component_id"] == "onboard_mic"}
    assert roles == {"WS", "DIN"}


def test_board_without_onboard_peripherals_seeds_nothing(lib):
    frag = seed_onboard_components(lib.board("esp32-devkitc-v4"), lib)
    assert frag == {"components": [], "buses": [], "connections": [], "warnings": []}


# ---------------------------------------------------------------------------
# Extended peripheral types
# ---------------------------------------------------------------------------

def test_addressable_led_picks_chipset_from_key(lib):
    frag = seed_onboard_components(lib.board("m5stack-atom-matrix"), lib)
    led = next(c for c in frag["components"] if c["library_id"] == "esp32_rmt_led_strip")
    assert led["params"]["chipset"] == "SK6812"
    assert led["params"]["num_leds"] == 25  # 5x5 matrix


def test_plain_led_uses_gpio_output(lib):
    # The ESP32-C3 SuperMini's bare `led` is a plain GPIO LED, not a strip.
    frag = seed_onboard_components(lib.board("esp32-c3-supermini"), lib)
    assert "gpio_output" in [c["library_id"] for c in frag["components"]]
    assert "esp32_rmt_led_strip" not in [c["library_id"] for c in frag["components"]]


def test_imu_honours_its_own_i2c_pins(lib):
    # Atom Matrix puts the IMU on GPIO25/21, not the default Grove bus.
    frag = seed_onboard_components(lib.board("m5stack-atom-matrix"), lib)
    imu_bus = next(b for b in frag["buses"] if b["id"] == "i2c_imu")
    assert (imu_bus["sda"], imu_bus["scl"]) == ("GPIO25", "GPIO21")


def test_ttgo_lora_seeds_radio_oled_adc(lib):
    frag = seed_onboard_components(lib.board("ttgo-lora32-v1"), lib)
    libs = {c["library_id"] for c in frag["components"]}
    assert {"sx127x", "ssd1306", "adc"} <= libs


def test_gps_uart_crosses_over_and_avoids_reserved_id(lib):
    # GPS TX (GPIO34, input-only) must land on the MCU rx; the MCU tx
    # (GPIO12) drives the GPS rx. The bus id must not be a reserved uartN.
    frag = seed_onboard_components(lib.board("ttgo-t-beam"), lib)
    bus = next(b for b in frag["buses"] if b["type"] == "uart")
    assert bus["id"] == "gps_uart"
    assert bus["tx"] == "GPIO12" and bus["rx"] == "GPIO34"


def test_unmapped_peripherals_warn_not_fail(lib):
    # axp192 (PMIC) has no component; it should warn, not break seeding.
    frag = seed_onboard_components(lib.board("ttgo-t-beam"), lib)
    assert any("axp192" in w["text"] for w in frag["warnings"])
    assert {c["library_id"] for c in frag["components"]} == {"sx127x", "uart_gps", "gpio_input"}


@pytest.mark.parametrize("board_id", [
    "esp32-c3-devkitm-1", "esp32-c3-supermini", "esp32-s3-devkitc-1",
    "m5stack-atom-echo", "m5stack-atom-matrix", "m5stack-atomu",
    "m5stack-atoms3-lite", "ttgo-lora32-v1", "ttgo-t-beam",
])
def test_every_board_seed_renders(lib, board_id):
    """Every board's seeded design renders without error. The
    esphome-config gate proves it validates upstream too."""
    frag = seed_onboard_components(lib.board(board_id), lib)
    design = Design.model_validate(_full_design(board_id, frag))
    render_yaml(design, lib)  # raises on a bad template / missing bus


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
