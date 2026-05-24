from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from wirestudio.library import Radio, default_library
from wirestudio.model import Design, LoRaWAN

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads(
    (REPO_ROOT / "wirestudio" / "schema" / "design.schema.json").read_text()
)

RADIO_BOARDS = {
    "ttgo-lora32-v1": ("sx1276", "SX1276"),
    "ttgo-t-beam": ("sx1276", "SX1276"),
    "heltec-wifi-lora32-v2": ("sx1276", "SX1276"),
    "heltec-wifi-lora32-v3": ("sx1262", "SX1262"),
}


def _base_design(**extra) -> Design:
    return Design(
        schema_version="0.1",
        id="x",
        name="X",
        board={"library_id": "ttgo-lora32-v1", "mcu": "esp32"},
        power={"supply": "usb", "rail_voltage_v": 3.3},
        **extra,
    )


def test_target_defaults_to_esphome():
    d = _base_design()
    assert d.target == "esphome"
    assert d.lorawan is None


def test_lorawan_defaults_pin_to_us915_subband2():
    d = _base_design(target="lorawan", lorawan={})
    assert d.lorawan.region == "US915"
    assert d.lorawan.sub_band == 2
    assert d.lorawan.provisioning == "runtime_serial"
    assert d.lorawan.dev_eui is None


def test_lorawan_rejects_secret_keys():
    # AppKey/NwkKey are secrets and must never be modellable in design.json.
    with pytest.raises(ValidationError):
        LoRaWAN(app_key="00" * 16)


def test_lorawan_design_validates_against_schema():
    d = _base_design(target="lorawan", lorawan={})
    jsonschema.validate(d.model_dump(mode="json", exclude_none=True), SCHEMA)


def test_all_boards_still_load():
    # Regression guard: the new radio: field must not break any board YAML.
    boards = default_library().list_boards()
    assert len(boards) >= len(RADIO_BOARDS)


@pytest.mark.parametrize("board_id,expected", RADIO_BOARDS.items())
def test_radio_boards_expose_radio(board_id, expected):
    chip, radiolib_class = expected
    board = default_library().board(board_id)
    assert board.has_radio
    assert board.radio.chip == chip
    assert board.radio.radiolib_class == radiolib_class
    assert board.radio.pins.cs and board.radio.pins.rst


def test_sx126x_carries_busy_and_dio1():
    radio = default_library().board("heltec-wifi-lora32-v3").radio
    assert radio.pins.busy is not None
    assert radio.pins.dio1 is not None
    assert radio.dio2_as_rf_switch is True
    assert radio.tcxo_voltage > 0


def test_non_radio_board_has_no_radio():
    board = default_library().board("esp32-devkitc-v4")
    assert not board.has_radio
    assert board.radio is None


def test_sx1262_requires_busy_and_dio1():
    with pytest.raises(ValidationError):
        Radio.model_validate(
            {
                "chip": "sx1262",
                "radiolib_class": "SX1262",
                "pins": {"cs": "GPIO8", "rst": "GPIO12", "dio1": "GPIO14"},
            }
        )


def test_sx127x_requires_dio0():
    with pytest.raises(ValidationError):
        Radio.model_validate(
            {
                "chip": "sx1276",
                "radiolib_class": "SX1276",
                "pins": {"cs": "GPIO18", "rst": "GPIO23", "busy": "GPIO13"},
            }
        )
