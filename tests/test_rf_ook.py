"""433 MHz OOK receive on an SX127x, `!lambda` strings anywhere in the
document, and multi-word component search -- the gaps a real
lora32-433-receiver design ran into."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from wirestudio.agent.tools import _run_search_components
from wirestudio.generate.yaml_gen import render_yaml
from wirestudio.model import Design

EXAMPLES = Path(__file__).resolve().parent.parent / "wirestudio" / "examples"


class _Tagged(yaml.SafeLoader):
    pass


_Tagged.add_constructor("!lambda", lambda loader, node: ("lambda", loader.construct_scalar(node)))
_Tagged.add_constructor("!secret", lambda loader, node: ("secret", loader.construct_scalar(node)))


def _render(doc: dict, library) -> dict:
    return yaml.load(render_yaml(Design.model_validate(doc), library), Loader=_Tagged)


@pytest.fixture
def lora32():
    return json.loads((EXAMPLES / "ttgo-lora32.json").read_text())


def _radio(doc: dict) -> dict:
    return next(c for c in doc["components"] if c["library_id"] == "sx127x")


@pytest.mark.parametrize("modulation, expected", [("OOK", False), ("FSK", True)])
def test_fsk_ook_get_the_settings_esphome_requires(lora32, library, modulation, expected):
    _radio(lora32)["params"].update(modulation=modulation, rx_floor=-90)
    radio = _render(lora32, library)["sx127x"]
    assert radio["bitsync"] is expected and radio["packet_mode"] is expected
    assert radio["rx_floor"] == -90


def test_lora_output_is_unchanged(lora32, library):
    radio = _render(lora32, library)["sx127x"]
    assert not {"bitsync", "packet_mode", "rx_floor"} & set(radio)


def test_explicit_bitsync_wins(lora32, library):
    _radio(lora32)["params"].update(modulation="OOK", bitsync=True)
    assert _render(lora32, library)["sx127x"]["bitsync"] is True


def test_remote_receiver_takes_rf_timing_and_rc_switch(lora32, library):
    lora32["components"].append({
        "id": "rf_rx", "library_id": "remote_receiver", "label": "433 MHz receiver",
        "params": {"inverted": False, "dump": "rc_switch", "tolerance": "25%", "filter": "250us",
                   "idle": "4ms", "buffer_size": "2kb",
                   "on_rc_switch": {"code": "100010000000000010111110", "then": [{"logger.log": "rc"}]}},
    })
    lora32["connections"] += [
        {"component_id": "rf_rx", "pin_role": "VCC", "target": {"kind": "rail", "rail": "3V3"}},
        {"component_id": "rf_rx", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
        {"component_id": "rf_rx", "pin_role": "OUT", "target": {"kind": "gpio", "pin": "GPIO32"}},
    ]
    rx = _render(lora32, library)["remote_receiver"]
    assert rx["pin"]["inverted"] is False
    assert (rx["tolerance"], rx["filter"], rx["idle"], rx["buffer_size"]) == ("25%", "250us", "4ms", "2kb")
    assert rx["on_rc_switch"]["code"] == "100010000000000010111110"


@pytest.mark.parametrize("raw, body", [
    ("!lambda 'return id(x).state;'", "return id(x).state;"),
    ("!lambda return id(x).state;", "return id(x).state;"),
    ("!lambda return a: b;", "return a: b;"),
    ("!lambda 'return \"it''s\";'", 'return "it\'s";'),
    ('!lambda "return {\\"x\\"};"', 'return {"x"};'),
])
def test_extras_lambdas_render_as_tags(lora32, library, raw, body):
    doc = copy.deepcopy(lora32)
    doc["esphome_extras"] = {"interval": [{"interval": "1s", "then": [{"lambda": raw}]}]}
    out = _render(doc, library)
    assert out["interval"][0]["then"][0]["lambda"] == ("lambda", body)


def test_a_lambda_in_an_automation_param_is_a_tag(lora32, library):
    """The ttgo-lora32 example's on_packet lambda contains `: `, which used to
    leave it a quoted string that ESPHome would compile as `!lambda ESP_LOGD`."""
    then = _render(lora32, library)["sx127x"]["on_packet"]["then"][0]["lambda"]
    assert then[0] == "lambda" and then[1].startswith("ESP_LOGD(")


def test_multi_word_search_matches_by_word(library):
    ids = [m["library_id"] for m in _run_search_components({}, library, query="remote receiver 433 rf")["matches"]]
    assert ids[0] == "remote_receiver" and "rf_bridge" in ids[:3]
