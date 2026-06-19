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


# --- W1: Design.lorawan IR additions for the external-component path --------
# Adds an ordered `payload` list and broadens `region` to the four bands
# `lorawan-for-esphome` will support, without touching the standalone Arduino
# fields. See docs/lorawan/workflow-integration.md.

def test_lorawan_payload_defaults_to_empty():
    d = _base_design(target="esphome", lorawan={})
    assert d.lorawan.payload == []


def test_lorawan_payload_round_trips_through_the_model():
    d = _base_design(target="esphome", lorawan={
        "payload": [{"sensor": "battery"}, {"sensor": "temp"}],
    })
    assert [f.sensor for f in d.lorawan.payload] == ["battery", "temp"]


def test_lorawan_payload_field_rejects_unknown_keys():
    # PayloadField is strict (extra="forbid"); a typoed key (e.g. bytes:)
    # raises rather than silently dropping data the codec would need.
    with pytest.raises(ValidationError):
        LoRaWAN(payload=[{"sensor": "x", "bytes": 4}])


def test_lorawan_payload_field_requires_sensor():
    with pytest.raises(ValidationError):
        LoRaWAN(payload=[{}])


@pytest.mark.parametrize("region", ["US915", "EU868", "AU915", "AS923"])
def test_lorawan_region_accepts_supported_bands(region):
    d = _base_design(target="esphome", lorawan={"region": region})
    assert d.lorawan.region == region


def test_lorawan_region_rejects_unknown_band():
    with pytest.raises(ValidationError):
        LoRaWAN(region="MOON915")


def test_lorawan_payload_design_validates_against_schema():
    d = _base_design(target="esphome", lorawan={
        "region": "EU868",
        "sub_band": 0,
        "payload": [{"sensor": "battery"}],
    })
    jsonschema.validate(d.model_dump(mode="json", exclude_none=True), SCHEMA)


def test_lorawan_payload_field_rejects_unknown_keys_at_schema_level():
    # The JSON Schema mirrors the model: extra keys on a payload item fail
    # schema validation, not just model parsing. Catches a `bytes:` typo even
    # for callers that bypass the pydantic model.
    raw = {
        "schema_version": "0.1", "id": "x", "name": "X",
        "board": {"library_id": "ttgo-lora32-v1", "mcu": "esp32"},
        "power": {"supply": "usb", "rail_voltage_v": 3.3},
        "lorawan": {"payload": [{"sensor": "battery", "bytes": 4}]},
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, SCHEMA)


# --- W2: generator emits external_components: + lorawan: + payload bindings -

from wirestudio.generate.yaml_gen import render_yaml  # noqa: E402

LORAWAN_EXAMPLE = REPO_ROOT / "wirestudio" / "examples" / "lorawan-battery-uplink.json"


def test_lorawan_payload_design_matches_golden():
    """Round-trip: the W2 worked example renders byte-identical to its
    pinned golden. Catches drift in any of the four moving pieces --
    external_components ref, radio config emission, !secret routing, payload
    sensor binding -- in one assertion."""
    d = Design.model_validate(json.loads(LORAWAN_EXAMPLE.read_text()))
    lib = default_library()
    expected = (REPO_ROOT / "tests" / "golden" / "lorawan-battery-uplink.yaml").read_text()
    assert render_yaml(d, lib) == expected


def test_lorawan_emission_skipped_when_payload_empty():
    """Without `payload`, the generator MUST NOT emit external_components or
    a lorawan: block -- existing non-LoRaWAN designs render byte-identical."""
    d = Design(
        schema_version="0.1", id="x", name="X",
        board={"library_id": "ttgo-lora32-v1", "mcu": "esp32"},
        power={"supply": "usb", "rail_voltage_v": 3.3},
        target="esphome",
        # No lorawan block at all
    )
    yaml = render_yaml(d, default_library())
    assert "external_components" not in yaml
    assert "lorawan:" not in yaml


def test_lorawan_emission_skipped_when_lorawan_block_has_empty_payload():
    """A lorawan block with an empty payload list is treated the same as no
    block -- the W2 emission is gated on payload being non-empty, since an
    uplink with zero fields is meaningless."""
    d = Design(
        schema_version="0.1", id="x", name="X",
        board={"library_id": "ttgo-lora32-v1", "mcu": "esp32"},
        power={"supply": "usb", "rail_voltage_v": 3.3},
        target="esphome",
        lorawan={"payload": []},
    )
    yaml = render_yaml(d, default_library())
    assert "external_components" not in yaml
    assert "lorawan:" not in yaml


def test_lorawan_emission_pins_the_external_component_ref():
    """The generator pins lorawan-for-esphome at a known ref (commit SHA per
    the locked decision); the rendered YAML must carry both `source:` and
    `ref:` so a future bump is a one-line reviewed change."""
    d = Design.model_validate(json.loads(LORAWAN_EXAMPLE.read_text()))
    yaml = render_yaml(d, default_library())
    assert "source: github://moellere/lorawan-for-esphome" in yaml
    assert "ref: " in yaml


def test_lorawan_emission_uses_secret_references_for_keys():
    """Keys (dev_eui / join_eui / app_key) must render as !secret references,
    not literals -- the CLAUDE.md secrets-never-in-design.json rule applies
    to the rendered YAML too."""
    d = Design.model_validate(json.loads(LORAWAN_EXAMPLE.read_text()))
    yaml = render_yaml(d, default_library())
    for key in ("dev_eui", "join_eui", "app_key"):
        assert f"{key}: !secret {key}" in yaml


def test_lorawan_emission_reads_radio_config_from_board_library():
    """The radio block (chip, pins, optional tcxo/dio2-rf-switch) comes from
    the board library's `radio:` metadata -- not duplicated in design.json.
    Validates by comparing SX1276 (TTGO LoRa32 v1) and SX1262 (Heltec V3)
    boards: chip differs, pin set differs, and SX1262 carries tcxo +
    dio2_as_rf_switch."""
    sx1276 = Design(
        schema_version="0.1", id="x", name="X",
        board={"library_id": "ttgo-lora32-v1", "mcu": "esp32"},
        power={"supply": "usb", "rail_voltage_v": 3.3},
        target="esphome",
        lorawan={"payload": [{"sensor": "x"}]},
    )
    sx1262 = Design(
        schema_version="0.1", id="x", name="X",
        board={"library_id": "heltec-wifi-lora32-v3", "mcu": "esp32"},
        power={"supply": "usb", "rail_voltage_v": 3.3},
        target="esphome",
        lorawan={"payload": [{"sensor": "x"}]},
    )
    y1276 = render_yaml(sx1276, default_library())
    y1262 = render_yaml(sx1262, default_library())

    assert "chip: sx1276" in y1276
    assert "dio0_pin:" in y1276
    assert "tcxo_voltage" not in y1276

    assert "chip: sx1262" in y1262
    assert "dio1_pin:" in y1262
    assert "busy_pin:" in y1262
    assert "tcxo_voltage: 1.8" in y1262
    assert "dio2_as_rf_switch: true" in y1262


def test_lorawan_payload_emits_one_sensor_binding_per_field_in_order():
    """Each payload entry emits one `sensor: - platform: lorawan` binding in
    declaration order -- the codec contract relies on this."""
    d = Design(
        schema_version="0.1", id="x", name="X",
        board={"library_id": "ttgo-lora32-v1", "mcu": "esp32"},
        power={"supply": "usb", "rail_voltage_v": 3.3},
        target="esphome",
        lorawan={"payload": [{"sensor": "battery"}, {"sensor": "temp"}, {"sensor": "humidity"}]},
    )
    yaml = render_yaml(d, default_library())
    # Three platform: lorawan entries appear, and in the right order
    bindings = [line.strip() for line in yaml.splitlines() if "platform: lorawan" in line]
    assert len(bindings) == 3
    idx_b = yaml.index("sensor: battery")
    idx_t = yaml.index("sensor: temp")
    idx_h = yaml.index("sensor: humidity")
    assert idx_b < idx_t < idx_h


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
