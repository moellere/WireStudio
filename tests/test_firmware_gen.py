from __future__ import annotations

import pytest

from wirestudio.library import default_library
from wirestudio.model import Design
from wirestudio.targets.lorawan.firmware_gen import generate_firmware, write_firmware


def _design(board_id: str, **lorawan) -> Design:
    kw = {}
    if lorawan:
        kw["target"] = "lorawan"
        kw["lorawan"] = lorawan
    return Design(
        schema_version="0.1",
        id="dev1",
        name="Dev 1",
        board={"library_id": board_id, "mcu": "esp32"},
        power={"supply": "usb", "rail_voltage_v": 3.3},
        **kw,
    )


@pytest.fixture
def lib():
    return default_library()


def test_generates_two_files(lib):
    out = generate_firmware(_design("ttgo-lora32-v1"), lib)
    assert set(out) == {"platformio.ini", "src/main.cpp"}


def test_platformio_ini_pins_board_and_deps(lib):
    ini = generate_firmware(_design("ttgo-lora32-v1"), lib)["platformio.ini"]
    assert "board = ttgo-lora32-v1" in ini
    assert "jgromes/RadioLib@^7.6.0" in ini
    assert "ropg/LoRaWAN_ESP32@^1.3.0" in ini


def test_sx1276_constructor_wiring(lib):
    # TTGO LoRa32 V1: cs=18, dio0=26, rst=23, no dio1 -> RADIOLIB_NC.
    cpp = generate_firmware(_design("ttgo-lora32-v1"), lib)["src/main.cpp"]
    assert "SX1276 radio = new Module(18, 26, 23, RADIOLIB_NC);" in cpp
    assert "setTCXO" not in cpp  # SX127x has no TCXO branch
    assert "persist.manage(&radio)" in cpp  # nonce/session persistence
    assert "WS_SUBBAND  = 2;" in cpp  # sub-band 2 pinned


def test_sx1262_constructor_and_tcxo(lib):
    # Heltec V3: cs=8, dio1=14, rst=12, busy=13; TCXO + RF-switch branch.
    cpp = generate_firmware(_design("heltec-wifi-lora32-v3"), lib)["src/main.cpp"]
    assert "SX1262 radio = new Module(8, 14, 12, 13);" in cpp
    assert "radio.setTCXO(1.8);" in cpp
    assert "radio.setDio2AsRfSwitch(true);" in cpp


def test_subband_override_flows_to_firmware(lib):
    cpp = generate_firmware(_design("ttgo-lora32-v1", sub_band=1), lib)["src/main.cpp"]
    assert "WS_SUBBAND  = 1;" in cpp


def test_join_eui_substituted(lib):
    cpp = generate_firmware(
        _design("ttgo-lora32-v1", join_eui="70b3d57ed0000000"), lib
    )["src/main.cpp"]
    assert "0x70b3d57ed0000000ULL" in cpp


def test_oled_init_recovers_bus_and_is_non_blocking(lib):
    # The onboard SSD1306 must not be able to wedge boot. A held-low SDA
    # survives a transaction timeout, so recover the bus (clock SCL to release
    # the slave) BEFORE Wire.begin(), then probe for an ACK before display
    # init, and gate the loop() refresh on readiness (issue #80).
    cpp = generate_firmware(_design("ttgo-lora32-v1"), lib)["src/main.cpp"]
    assert "digitalRead(21) == LOW" in cpp  # bus-recovery checks a stuck SDA
    assert "oledPresent = (Wire.endTransmission() == 0)" in cpp
    assert "if (oledPresent && display.begin(" in cpp
    assert "if (oledReady) {" in cpp


def test_nooled_board_emits_no_oled_code(lib):
    # The OLED-disabled board profile must generate firmware with no display
    # bring-up at all (issue #80 escape hatch).
    out = generate_firmware(_design("ttgo-lora32-v2-nooled"), lib)
    cpp = out["src/main.cpp"]
    assert "display.begin(" not in cpp
    assert "Adafruit_SSD1306" not in cpp
    assert "board = ttgo-lora32-v21" in out["platformio.ini"]
    assert "Adafruit SSD1306" not in out["platformio.ini"]  # lib dep dropped too


def test_ttgo_v2_uses_v21_platformio_board(lib):
    # v2.1 (T3 v1.6.1) is electrically identical to v1 but maps to its own
    # PlatformIO board key.
    out = generate_firmware(_design("ttgo-lora32-v2"), lib)
    assert "board = ttgo-lora32-v21" in out["platformio.ini"]
    assert "SX1276 radio = new Module(18, 26, 23, RADIOLIB_NC);" in out["src/main.cpp"]


def test_non_radio_board_raises(lib):
    with pytest.raises(ValueError, match="no radio"):
        generate_firmware(_design("esp32-devkitc-v4"), lib)


def test_unknown_board_raises(lib):
    with pytest.raises(FileNotFoundError):
        generate_firmware(_design("no-such-board"), lib)


def test_write_firmware_creates_project(lib, tmp_path):
    write_firmware(_design("ttgo-lora32-v1"), lib, tmp_path)
    assert (tmp_path / "platformio.ini").is_file()
    assert (tmp_path / "src" / "main.cpp").is_file()
