from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.library import default_library
from wirestudio.model import Design
from wirestudio.targets import get_target
from wirestudio.targets.tasmota import FUNC, _CHIP_SLOTS, build_template

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "wirestudio" / "examples"


def _design(stem: str) -> Design:
    return Design.model_validate(json.loads((EXAMPLES / f"{stem}.json").read_text()))


@pytest.fixture(scope="module")
def lib():
    return default_library()


def test_smart_plug_matches_sonoff_convention(lib):
    template, warnings = build_template(_design("smart-plug"), lib)
    assert template["GPIO"] == [160, 3072, 0, 3104, 0, 0, 0, 0, 224, 0, 0, 0, 0, 0]
    assert template["BASE"] == 18
    assert template["FLAG"] == 0
    assert warnings == []


def test_attic_logger_dht_and_i2c(lib):
    template, _ = build_template(_design("attic-logger"), lib)
    gpio = template["GPIO"]
    assert FUNC["DHT22"] in gpio
    assert FUNC["I2C_SDA"] in gpio
    assert FUNC["I2C_SCL"] in gpio


def test_analog_node_esp32_layout(lib):
    template, warnings = build_template(_design("analog-node"), lib)
    slots = _CHIP_SLOTS["esp32"]
    assert len(template["GPIO"]) == len(slots) == 36
    assert template["GPIO"][slots.index(21)] == FUNC["I2C_SDA"]
    assert template["GPIO"][slots.index(22)] == FUNC["I2C_SCL"]
    assert template["GPIO"][slots.index(34)] == FUNC["ADC_Input"]
    assert template["BASE"] == 1
    # ADS1115 hub channels have no Tasmota equivalent and warn.
    assert any("ads1115_channel" in w for w in warnings)


def test_relay_units_number_sequentially(lib):
    d = _design("smart-plug")
    raw = json.loads((EXAMPLES / "smart-plug.json").read_text())
    raw["components"].append({"id": "relay2", "library_id": "gpio_output", "label": "R2", "params": {}})
    raw["connections"].append(
        {"component_id": "relay2", "pin_role": "OUT", "target": {"kind": "gpio", "pin": "GPIO13"}}
    )
    template, _ = build_template(Design.model_validate(raw), lib)
    gpio = template["GPIO"]
    assert FUNC["Relay"] in gpio
    assert FUNC["Relay"] + 1 in gpio
    assert d  # smart-plug baseline untouched


def test_every_templatable_example_is_structurally_valid(lib):
    target = get_target("tasmota")
    known_bases = set(FUNC.values())
    checked = 0
    for path in sorted(EXAMPLES.glob("*.json")):
        design = Design.model_validate(json.loads(path.read_text()))
        board = lib.board(design.board.library_id)
        if board.chip_variant not in _CHIP_SLOTS:
            continue
        template, _ = build_template(design, lib)
        assert len(template["GPIO"]) == len(_CHIP_SLOTS[board.chip_variant]), path.name
        for v in template["GPIO"]:
            assert v == 0 or any(0 <= v - b < 8 for b in known_bases), (path.name, v)
        checked += 1
    assert checked > 10
    assert "smart-plug" in " ".join(p.stem for p in EXAMPLES.glob("*.json"))
    assert target.board_ids(lib)


def test_target_registry_and_component_ids(lib):
    target = get_target("tasmota")
    comps = target.component_ids(lib)
    assert "gpio_output" in comps
    assert "bme280" in comps  # i2c autodetect
    assert "sx127x" not in comps


def test_template_endpoint():
    client = TestClient(create_app())
    design = json.loads((EXAMPLES / "smart-plug.json").read_text())
    r = client.post("/tasmota/template", json=design)
    assert r.status_code == 200
    body = r.json()
    assert body["template"]["GPIO"][1] == 3072
    assert body["warnings"] == []


def test_firmware_endpoint_serves_proxied_image(monkeypatch):
    import wirestudio.targets.tasmota as T
    monkeypatch.setattr(T, "_fetch_firmware", lambda url: b"BIN" + url.encode()[-10:])
    client = TestClient(create_app())
    r = client.get("/tasmota/firmware?chip=esp32")
    assert r.status_code == 200
    assert r.headers["x-flash-offset"] == "0"
    assert r.content.startswith(b"BIN")


def test_firmware_endpoint_unknown_chip_422():
    client = TestClient(create_app())
    assert client.get("/tasmota/firmware?chip=rp2040").status_code == 422


def test_firmware_endpoint_upstream_failure_502(monkeypatch):
    import wirestudio.targets.tasmota as T

    def boom(url):
        raise RuntimeError("nope")

    monkeypatch.setattr(T, "_fetch_firmware", boom)
    client = TestClient(create_app())
    r = client.get("/tasmota/firmware?chip=esp8266")
    assert r.status_code == 502


def test_co2_display_resolves_d_labels_and_uart_funcs(lib):
    template, warnings = build_template(_design("co2-display"), lib)
    slots = _CHIP_SLOTS["esp8266"]
    gpio = template["GPIO"]
    # TM1637 on D1/D2 = GPIO5/GPIO4, not GPIO1/GPIO2.
    assert gpio[slots.index(5)] == FUNC["TM1637_CLK"]
    assert gpio[slots.index(4)] == FUNC["TM1637_DIO"]
    # MH-Z19 over the software UART: bus tx D6 = GPIO12, rx D5 = GPIO14.
    assert gpio[slots.index(12)] == FUNC["MHZ_TXD"]
    assert gpio[slots.index(14)] == FUNC["MHZ_RXD"]
    # Two bus connections (TX + RX) map the bus once -- no duplicate warnings.
    assert warnings == []


def test_access_panel_wiegand_and_servo(lib):
    template, _ = build_template(_design("access-panel"), lib)
    slots = _CHIP_SLOTS["esp32"]
    gpio = template["GPIO"]
    assert gpio[slots.index(32)] == FUNC["Wiegand_D0"]
    assert gpio[slots.index(33)] == FUNC["Wiegand_D1"]
    assert gpio[slots.index(13)] == FUNC["PWM"]
    assert gpio[slots.index(26)] == FUNC["Relay"]


def test_output_hub_shift_register(lib):
    template, _ = build_template(_design("output-hub"), lib)
    slots = _CHIP_SLOTS["esp32"]
    gpio = template["GPIO"]
    assert gpio[slots.index(25)] == FUNC["Shift595_SER"]
    assert gpio[slots.index(26)] == FUNC["Shift595_SRCLK"]
    assert gpio[slots.index(27)] == FUNC["Shift595_RCLK"]


def test_presence_media_node_ld2410_and_ir(lib):
    template, _ = build_template(_design("presence-media-node"), lib)
    slots = _CHIP_SLOTS["esp32"]
    gpio = template["GPIO"]
    assert gpio[slots.index(17)] == FUNC["LD2410_TX"]
    assert gpio[slots.index(16)] == FUNC["LD2410_RX"]
    assert gpio[slots.index(25)] == FUNC["IRrecv"]
