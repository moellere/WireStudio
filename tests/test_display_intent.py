import json
from pathlib import Path

import pytest
import yaml

from wirestudio.generate.display_intent import lower_show, validate_show
from wirestudio.generate.yaml_gen import render_yaml
from wirestudio.intent import MELODIES, validate_automations
from wirestudio.library import default_library
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "wirestudio" / "examples"


def _design(stem: str) -> Design:
    return Design.model_validate(json.loads((EXAMPLES / f"{stem}.json").read_text()))


@pytest.fixture(scope="module")
def lib():
    return default_library()


def test_seven_segment_show_lowers_to_printf(lib):
    parsed = yaml.unsafe_load(render_yaml(_design("co2-display"), lib))
    lam = parsed["display"][0]["lambda"]
    assert 'it.printf("%4.0f", id(co2meter_co2).state);' == lam.strip()


def test_pixel_show_emits_font_time_and_strftime(lib):
    parsed = yaml.unsafe_load(render_yaml(_design("oled"), lib))
    assert parsed["font"][0]["file"] == "gfonts://Roboto"
    assert parsed["font"][0]["id"] == "ws_show_font"
    assert any(t.get("id") == "ws_show_time" for t in parsed["time"])
    lam = parsed["display"][0]["lambda"]
    assert 'it.printf(0, y, id(ws_show_font), "wirestudio");' in lam
    assert 'it.strftime(0, y, id(ws_show_font), "Time: %H:%M", id(ws_show_time).now());' in lam


def test_explicit_lambda_wins_over_show(lib):
    raw = json.loads((EXAMPLES / "oled.json").read_text())
    for c in raw["components"]:
        if c["library_id"] == "ssd1306":
            c["params"]["lambda_"] = 'it.print(0, 0, id(f), "custom");'
    patches, extras = lower_show(Design.model_validate(raw), lib)
    assert patches == {}
    assert extras == {}


def test_character_dialect_prints_rows(lib):
    raw = json.loads((EXAMPLES / "oled.json").read_text())
    # Swap the display for an LCD; character dialect prints into rows, no font.
    for c in raw["components"]:
        if c["library_id"] == "ssd1306":
            c["library_id"] = "lcd_pcf8574"
            c["params"] = {"show": [
                {"kind": "text", "text": "hello"},
                {"kind": "time", "format": "%H:%M"},
            ]}
    patches, extras = lower_show(Design.model_validate(raw), lib)
    (patch,) = patches.values()
    assert 'it.printf(0, 0, "hello");' in patch["lambda_"]
    assert 'it.strftime(0, 1, "%H:%M", id(ws_show_time).now());' in patch["lambda_"]
    assert "font" not in extras


def test_validate_show_flags_unknown_source_and_channel(lib):
    raw = json.loads((EXAMPLES / "co2-display.json").read_text())
    for c in raw["components"]:
        if c["library_id"] == "tm1637":
            c["params"]["show"] = [
                {"kind": "value", "source": "ghost"},
                {"kind": "value", "source": "co2meter", "channel": "particulates"},
                {"kind": "wat"},
            ]
    codes = [w.code for w in validate_show(Design.model_validate(raw), lib)]
    assert "show_unknown_source" in codes
    assert "show_unknown_channel" in codes
    assert "show_unknown_widget" in codes
    assert "show_too_many_widgets" in codes


def test_play_action_resolves_named_melody(lib):
    parsed = yaml.unsafe_load(render_yaml(_design("co2-display"), lib))
    ranges = parsed["sensor"][0]["co2"]["on_value_range"]
    assert ranges[0]["above"] == 1200
    play = ranges[0]["then"][0]["rtttl.play"]
    assert play["id"] == "alert_buzzer"
    assert play["rtttl"] == MELODIES["alarm"]
    assert "song" not in play


def test_unknown_song_warns_and_drops(lib):
    raw = json.loads((EXAMPLES / "co2-display.json").read_text())
    raw["automations"][0]["actions"][0]["args"]["song"] = "freebird"
    d = Design.model_validate(raw)
    codes = [w.code for w in validate_automations(d, lib)]
    assert "automation_unknown_song" in codes
    parsed = yaml.unsafe_load(render_yaml(d, lib))
    assert "on_value_range" not in parsed["sensor"][0]["co2"]


def test_play_without_song_or_rtttl_warns(lib):
    raw = json.loads((EXAMPLES / "co2-display.json").read_text())
    raw["automations"][0]["actions"][0]["args"] = {}
    codes = [w.code for w in validate_automations(Design.model_validate(raw), lib)]
    assert "automation_play_needs_song" in codes
