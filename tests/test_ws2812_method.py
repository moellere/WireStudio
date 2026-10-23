"""The WS2812 template leaves the neopixelbus method to ESPHome unless set.

A fixed ESP8266_UART1 default only validates on an ESP8266 with DIN on
GPIO2; ESPHome's own default picks DMA, UART or bit-bang from the pin and
RMT or I2S on an ESP32."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from wirestudio.generate.yaml_gen import render_yaml
from wirestudio.library import default_library
from wirestudio.model import Design

EXAMPLE = Path(__file__).resolve().parent.parent / "wirestudio" / "examples" / "motion-turns-on-light.json"


@pytest.fixture
def library():
    return default_library()


def _light(library, board: str, pin: str, method: str | None) -> dict:
    d = json.loads(EXAMPLE.read_text())
    b = library.board(board)
    d["board"] = {"library_id": board, "mcu": b.mcu, "framework": b.framework}
    for c in d["components"]:
        if c["library_id"] == "ws2812b":
            c["params"].pop("method", None)
            if method:
                c["params"]["method"] = method
    for c in d["connections"]:
        if c["pin_role"] == "DIN":
            c["target"] = {"kind": "gpio", "pin": pin}
    out = yaml.safe_load(render_yaml(Design.model_validate(copy.deepcopy(d)), library))
    return next(l for l in out["light"] if l["platform"] == "neopixelbus")


@pytest.mark.parametrize("board, pin", [("wemos-d1-mini", "D1"), ("esp32-devkitc-v4", "GPIO13")])
def test_no_method_unless_set(library, board, pin):
    assert "method" not in _light(library, board, pin, None)


def test_a_set_method_is_kept(library):
    assert _light(library, "wemos-d1-mini", "D1", "BIT_BANG")["method"] == "BIT_BANG"
