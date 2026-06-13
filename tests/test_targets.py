from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.library import default_library
from wirestudio.model import Design
from wirestudio.targets import get_target, register, target_ids
from wirestudio.targets.esphome import EsphomeTarget

RADIO_BOARD_IDS = {
    "ttgo-lora32-v1", "ttgo-lora32-v2", "ttgo-lora32-v2-nooled", "ttgo-t-beam",
    "heltec-wifi-lora32-v2", "heltec-wifi-lora32-v3",
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _design(board_id: str, **extra) -> dict:
    return Design(
        schema_version="0.1",
        id="d",
        name="D",
        board={"library_id": board_id, "mcu": "esp32"},
        power={"supply": "usb", "rail_voltage_v": 3.3},
        **extra,
    ).model_dump(mode="json", exclude_none=True)


def test_both_targets_registered():
    assert target_ids() == ["esphome", "lorawan"]


def test_register_rejects_duplicate():
    with pytest.raises(ValueError):
        register(EsphomeTarget())


def test_get_unknown_target_raises():
    with pytest.raises(KeyError):
        get_target("does-not-exist")


def test_esphome_offers_all_boards():
    lib = default_library()
    assert set(get_target("esphome").board_ids(lib)) == {b.id for b in lib.list_boards()}


def test_lorawan_offers_only_radio_boards():
    lib = default_library()
    assert set(get_target("lorawan").board_ids(lib)) == RADIO_BOARD_IDS


def test_lorawan_validate_flags_non_radio_board():
    lib = default_library()
    d = Design.model_validate(_design("esp32-devkitc-v4", target="lorawan", lorawan={}))
    codes = {w.code for w in get_target("lorawan").validate(d, lib)}
    assert "lorawan_board_no_radio" in codes


def test_lorawan_validate_flags_unconfigured():
    lib = default_library()
    d = Design.model_validate(_design("ttgo-lora32-v1", target="lorawan"))
    codes = {w.code for w in get_target("lorawan").validate(d, lib)}
    assert "lorawan_unconfigured" in codes


def test_lorawan_validate_clean_on_radio_board_with_config():
    lib = default_library()
    d = Design.model_validate(_design("ttgo-lora32-v1", target="lorawan", lorawan={}))
    assert get_target("lorawan").validate(d, lib) == []


def test_lorawan_validate_warns_gps_on_console_uart():
    lib = default_library()
    # GPS on GPIO3/1 = U0RXD/U0TXD on the classic ESP32 -> floods the prompt.
    d = Design.model_validate(_design(
        "heltec-wifi-lora32-v2", target="lorawan",
        lorawan={"gps": {"rx_pin": "GPIO3", "tx_pin": "GPIO1"}},
    ))
    codes = {w.code for w in get_target("lorawan").validate(d, lib)}
    assert "lorawan_gps_on_console_uart" in codes
    # Safe pins -> no such warning.
    d2 = Design.model_validate(_design(
        "heltec-wifi-lora32-v2", target="lorawan",
        lorawan={"gps": {"rx_pin": "GPIO23", "tx_pin": "GPIO17"}},
    ))
    assert "lorawan_gps_on_console_uart" not in {w.code for w in get_target("lorawan").validate(d2, lib)}


def test_esphome_validate_adds_nothing():
    lib = default_library()
    d = Design.model_validate(_design("esp32-devkitc-v4"))
    assert get_target("esphome").validate(d, lib) == []


# --- API wiring -----------------------------------------------------------


def test_boards_endpoint_unfiltered_returns_all(client):
    all_ids = {b["id"] for b in client.get("/library/boards").json()}
    assert all_ids >= RADIO_BOARD_IDS
    assert "esp32-devkitc-v4" in all_ids  # a non-radio board is present


def test_boards_endpoint_lorawan_filter(client):
    ids = {b["id"] for b in client.get("/library/boards?target=lorawan").json()}
    assert ids == RADIO_BOARD_IDS


def test_boards_endpoint_esphome_filter_matches_unfiltered(client):
    all_ids = {b["id"] for b in client.get("/library/boards").json()}
    esphome_ids = {b["id"] for b in client.get("/library/boards?target=esphome").json()}
    assert esphome_ids == all_ids


def test_boards_endpoint_unknown_target_422(client):
    assert client.get("/library/boards?target=bogus").status_code == 422


def test_validate_endpoint_surfaces_lorawan_warnings(client):
    body = _design("esp32-devkitc-v4", target="lorawan", lorawan={})
    r = client.post("/design/validate", json=body)
    assert r.status_code == 200
    codes = {w["code"] for w in r.json()["warnings"]}
    assert "lorawan_board_no_radio" in codes


def test_validate_endpoint_esphome_unchanged(client):
    body = _design("esp32-devkitc-v4")
    r = client.post("/design/validate", json=body)
    assert r.status_code == 200
    assert r.json()["warnings"] == []
