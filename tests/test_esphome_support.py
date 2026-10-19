"""The ESPHome support table: `docs/esphome-support.md` is what
`scripts/esphome_support.py` produces from the committed sweep results,
and the attribution reads ESPHome's error excerpt the way the gate
writes it."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "esphome_support.py"

spec = importlib.util.spec_from_file_location("esphome_support", SCRIPT)
es = importlib.util.module_from_spec(spec)
spec.loader.exec_module(es)


@pytest.fixture(scope="module")
def library():
    from wirestudio.library import default_library
    return default_library()


def test_committed_table_matches_the_committed_results():
    proc = subprocess.run([sys.executable, str(SCRIPT), "--check"],
                          cwd=REPO_ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_committed_results_cover_the_pin():
    versions = {json.loads(p.read_text())["esphome"] for p in es.RESULTS_DIR.glob("*.json")}
    assert es.pinned_version() in versions


_API_KEY_FAILURE = """Failed config

api: [source /tmp/x/garage-motion/garage-motion.yaml:11]
  encryption:

    The all-zeros key is reserved and provides no protection; omit the key.
    key: !secret api_key
INFO ESPHome 2026.9.1
"""

_COMPONENT_FAILURE = """Failed config

light.neopixelbus: [source /tmp/x/d.yaml:22]

  ESP8266 uart bus 1 only supports pin GPIO2.
  platform: neopixelbus
  variant: WS2812
  pin: D0
  num_leds: 30
  name: Porch strip
  id: porch_light
INFO ESPHome 2026.6.5
"""

_PLATFORM_FAILURE = """Failed config

sensor.bme280_i2c: [source /tmp/x/d.yaml:20]
  platform: bme280_i2c
  address: 0x76

  Unknown value 'nope', valid options are 'A', 'B'.
  iir_filter: nope
INFO ESPHome 2026.6.5
"""


def test_attribution_by_id(library):
    comps, named = es.attribute("motion-turns-on-light", _COMPONENT_FAILURE, library)
    assert (comps, named) == (["ws2812b"], True)


def test_attribution_by_platform(library):
    comps, named = es.attribute("garage-motion", _PLATFORM_FAILURE, library)
    assert (comps, named) == (["bme280"], True)


def test_unattributed_failure_charges_the_whole_example(library):
    comps, named = es.attribute("garage-motion", _API_KEY_FAILURE, library)
    assert (comps, named) == (["bme280", "hc-sr501"], False)


def test_first_error_line_skips_the_section_header():
    assert es.first_error_line(_COMPONENT_FAILURE) == "ESP8266 uart bus 1 only supports pin GPIO2."
    assert es.first_error_line(_PLATFORM_FAILURE).startswith("Unknown value 'nope'")


def _results(**per_version):
    out = {}
    for v, failing in per_version.items():
        examples = {"garage-motion": {"ok": True}, "motion-turns-on-light": {"ok": True}}
        for stem, detail in failing.items():
            examples[stem] = {"ok": False, "detail": detail}
        out[v] = {"esphome": v, "date": "2026-10-19", "examples": examples}
    return out


def test_supported_range_is_the_clean_run_around_the_pin(library, monkeypatch):
    monkeypatch.setattr(es, "pinned_version", lambda: "2026.6.5")
    a = es.analyse(_results(**{
        "2026.4.5": {"motion-turns-on-light": _COMPONENT_FAILURE},
        "2026.5.3": {}, "2026.6.5": {}, "2026.7.4": {},
        "2026.8.2": {"garage-motion": _PLATFORM_FAILURE},
    }), library)
    assert a["supported"] == ["2026.5.3", "2026.6.5", "2026.7.4"]
    assert a["needs"] == {"ws2812b": "2026.5.3"}
    assert a["breaks"] == {"bme280": "2026.8.2"}
    assert es.summary_line(a) == (
        "Supports ESPHome 2026.5 through 2026.7 (every bundled example validates; "
        "the pin is 2026.6.5). `ws2812b` needs 2026.5+; `bme280` breaks from 2026.8.")
    table = es.render(a)
    assert "| 2026.8.2 | 2026-10-19 | 1/2 | garage-motion: `bme280` |" in table
    assert "| `ws2812b` | 2026.4.5 | ESP8266 uart bus 1 only supports pin GPIO2. |" in table


def test_no_range_when_the_pin_fails(library, monkeypatch):
    monkeypatch.setattr(es, "pinned_version", lambda: "2026.6.5")
    a = es.analyse(_results(**{"2026.6.5": {"garage-motion": _API_KEY_FAILURE}}), library)
    assert a["supported"] == []
    assert es.summary_line(a).startswith("The pinned ESPHome 2026.6.5 is not in the sweep, or fails it")
    assert "garage-motion: `bme280`, `hc-sr501` (unattributed)" in es.render(a)
