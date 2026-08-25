"""The T-Beam LoRaWAN example: GPS + DHT22 + OLED on one board.

Covers the case the bare-board golden (t-beam.cpp) does not -- a design that
adds sensors the board file knows nothing about, alongside the two it does
(onboard GPS, AXP192 PMIC).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wirestudio.library import default_library
from wirestudio.model import Design
from wirestudio.targets.lorawan import codec
from wirestudio.targets.lorawan.firmware_gen import generate_firmware

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = REPO_ROOT / "wirestudio" / "examples" / "t-beam-lorawan.json"
GOLDEN = REPO_ROOT / "tests" / "golden"


@pytest.fixture
def lib():
    return default_library()


@pytest.fixture
def design():
    return Design.model_validate(json.loads(EXAMPLE.read_text()))


def test_it_is_a_standalone_lorawan_design(design):
    assert design.target == "lorawan"
    assert design.lorawan.region == "US915"
    assert design.lorawan.sub_band == 2
    # Keys never live in design.json; the serial prompt supplies them.
    assert design.lorawan.provisioning == "runtime_serial"


def test_the_pmic_supplies_the_cell_voltage(design, lib):
    """The T-Beam reads its 18650 through the AXP192, not an ADC divider --
    ttgo-t-beam declares no battery_adc. The PMIC is synthesized from the
    board rather than listed in the design."""
    resolved = {c.library_id for c in codec.resolve_components(design, lib)}
    assert "axp192" in resolved
    assert "battery_adc" not in resolved

    names = [f["name"] for f in codec.fields_for(design, lib)]
    assert "batt_mv" in names


def test_payload_carries_gps_environment_and_battery(design, lib):
    names = [f["name"] for f in codec.fields_for(design, lib)]
    assert names == ["uptime_s", "boot_count", "lat", "lon", "alt_m",
                     "sats", "fix_age_min", "temp_c", "humidity", "batt_mv"]


def test_the_datarate_floor_clears_the_payload(design, lib):
    """US915 DR0 caps the app payload at 11 bytes and this payload is 24, so
    a build that let ADR reach DR0 would have its uplinks rejected outright.
    24 is still well inside DR1's 53-byte cap, so adding fix_age_min cost no
    range."""
    size = codec.payload_size(codec.fields_for(design, lib))
    assert size == 24
    assert size <= 53, "still fits DR1"

    cpp = generate_firmware(design, lib)["src/main.cpp"]
    assert "node->setDatarate(1);" in cpp
    assert "setDatarate(0)" not in cpp


def test_radio_wiring_comes_from_the_board(design, lib):
    """cs=18, dio0=26, rst=23 per ttgo-t-beam. The design carries no radio
    component: the region drives the frequency, so an sx127x pinned to
    433 MHz would be a false statement on a US915 device."""
    cpp = generate_firmware(design, lib)["src/main.cpp"]
    assert "SX1276 radio = new Module(18, 26, 23, RADIOLIB_NC);" in cpp
    assert not any(c.library_id == "sx127x" for c in design.components)


def test_dht_and_oled_reach_the_firmware_on_their_wired_pins(design, lib):
    """The OLED reset is a connection, not a param -- worth pinning, since
    the constructor passes -1 and the pulse happens in setup()."""
    cpp = generate_firmware(design, lib)["src/main.cpp"]
    assert "DHT dht(13, DHT22);" in cpp
    assert "Wire.begin(21, 22);" in cpp
    assert "pinMode(4, OUTPUT);" in cpp


def test_profile_name_records_the_sensor_set(design, lib):
    assert codec.profile_name(design, lib) == (
        "wirestudio-ttgo-t-beam-us915-sub2-gps-batt-dht")


@pytest.mark.parametrize("key,golden", [
    ("src/main.cpp", "t-beam-lorawan.cpp"),
    ("platformio.ini", "t-beam-lorawan.ini"),
])
def test_firmware_matches_golden(design, lib, key, golden):
    assert generate_firmware(design, lib)[key] == (GOLDEN / golden).read_text()


def test_codec_matches_golden(design, lib):
    """generate_codec, not decode_js: the HA entity block rides along with
    the decoder and is what actually lands on the ChirpStack profile."""
    assert codec.generate_codec(design, lib) == (GOLDEN / "t-beam-lorawan.js").read_text()


def test_position_is_retained_when_the_fix_drops(design, lib):
    """lat/lon are published unconditionally, on purpose. On a vehicle,
    "where was it last seen" is the point -- a machine parked with its GNSS
    off should still report where it is. So the position is never cleared."""
    cpp = generate_firmware(design, lib)["src/main.cpp"]
    assert "(int32_t)(gps.location.lat() * 10000000.0)" in cpp
    assert "isValid() ? (int32_t)" not in cpp, "position must not be gated on a fix"


def test_fix_age_distinguishes_stale_from_fresh(design, lib):
    """Retaining the position means nothing marks a week-old fix as old, so
    the age rides alongside it. The isValid() guard is load-bearing: without
    it a device that never got a fix reports age 0 -- reading as perfectly
    fresh, which is the exact confusion this field exists to end."""
    cpp = generate_firmware(design, lib)["src/main.cpp"]
    assert "gps.location.isValid()" in cpp
    assert "65535" in cpp, "sentinel for 'never had a fix'"
    assert "60000UL" in cpp, "milliseconds -> minutes"

    names = [f["name"] for f in codec.fields_for(design, lib)]
    assert names.index("fix_age_min") == names.index("sats") + 1
