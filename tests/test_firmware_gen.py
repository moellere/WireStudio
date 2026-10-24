from __future__ import annotations

from pathlib import Path

import pytest

from wirestudio.library import default_library
from wirestudio.migrate import migrate
from wirestudio.model import Design
from wirestudio.targets.lorawan.codec import decode_js, fields_for
from wirestudio.targets.lorawan.firmware_gen import generate_firmware, write_firmware


def _design(board_id: str, **lorawan) -> Design:
    """A 0.3 design; `lorawan` may carry the retired gps / dht22 / oled
    blocks, which the migrator turns into components."""
    raw = {
        "schema_version": "0.3", "id": "dev1", "name": "Dev 1",
        "board": {"library_id": board_id, "mcu": "esp32"},
        "power": {"supply": "usb", "rail_voltage_v": 3.3},
    }
    if lorawan:
        raw["target"] = "lorawan"
        raw["lorawan"] = lorawan
    return Design.model_validate(migrate(raw).document)


def _design_with(*library_ids: str) -> Design:
    return Design.model_validate({
        "schema_version": "1.0", "id": "dev1", "name": "Dev 1", "target": "lorawan", "lorawan": {},
        "board": {"library_id": "ttgo-lora32-v2", "mcu": "esp32"},
        "power": {"supply": "usb", "rail_voltage_v": 3.3},
        "components": [{"id": cid, "library_id": cid, "label": cid, "params": {}} for cid in library_ids],
        "buses": [{"id": "i2c0", "type": "i2c", "sda": "GPIO21", "scl": "GPIO22"}],
        "connections": [{"component_id": cid, "pin_role": role, "target": {"kind": "bus", "bus_id": "i2c0"}}
                        for cid in library_ids for role in ("SDA", "SCL")],
    })


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


def test_oled_init_is_probed_and_non_blocking(lib):
    # The onboard SSD1306 must not be able to wedge boot: probe for an I2C
    # ACK before display.begin(), and gate the loop() refresh on readiness
    # (issue #80 -- a held-low SDA hung begin() into a TG1WDT reboot).
    cpp = generate_firmware(_design("ttgo-lora32-v1"), lib)["src/main.cpp"]
    assert "Wire.setTimeOut(50);" in cpp
    assert "Wire.endTransmission() == 0 && display.begin(" in cpp
    assert "if (oledReady) {" in cpp


def test_ttgo_omits_gpio16_oled_reset_pulse(lib):
    # issue #80 root cause: driving GPIO16 as the OLED reset wedges the chip at
    # boot on TTGO LoRa32, before Wire.begin(). The TTGO profiles carry no OLED
    # reset pin, so no reset pulse is emitted -- but the OLED is still used.
    for board in ("ttgo-lora32-v1", "ttgo-lora32-v2"):
        cpp = generate_firmware(_design(board), lib)["src/main.cpp"]
        assert "pinMode(16, OUTPUT)" not in cpp, board
        assert "explicit reset pulse" not in cpp, board
        assert "display.begin(" in cpp, board  # OLED still driven, just no reset
    # Heltec keeps its GPIO16 reset -- correct/required on that board.
    heltec = generate_firmware(_design("heltec-wifi-lora32-v2"), lib)["src/main.cpp"]
    assert "pinMode(16, OUTPUT)" in heltec


def test_ttgo_v2_uses_v21_platformio_board(lib):
    # v2.1 (T3 v1.6.1) is electrically identical to v1 but maps to its own
    # PlatformIO board key.
    out = generate_firmware(_design("ttgo-lora32-v2"), lib)
    assert "board = ttgo-lora32-v21" in out["platformio.ini"]
    assert "SX1276 radio = new Module(18, 26, 23, RADIOLIB_NC);" in out["src/main.cpp"]


def test_heltec_v4_seeded_gnss_powers_enable_and_fem(lib):
    # A seeded V4 LoRaWAN tracker: the GNSS enable pin (GPIO34, active low)
    # is driven LOW to power the module, the UART lands on 38/39, and the RF
    # front-end pins stay forced HIGH for the radio.
    from wirestudio.seed import seed_onboard_components

    frag = seed_onboard_components(lib.board("heltec-wifi-lora32-v4"), lib)
    design = Design(
        schema_version="0.1", id="v4t", name="V4 tracker",
        board={"library_id": "heltec-wifi-lora32-v4", "mcu": "esp32"},
        power={"supply": "usb", "rail_voltage_v": 3.3},
        target="lorawan", lorawan={"region": "US915", "sub_band": 2},
        components=frag["components"], buses=frag["buses"],
        connections=frag["connections"],
    )
    cpp = generate_firmware(design, lib)["src/main.cpp"]
    assert "pinMode(34, OUTPUT);" in cpp
    assert "digitalWrite(34, LOW);" in cpp  # active-low enable -> power on
    # Empirical (2026-08-30): the module's TX is GPIO39 -- MCU reads NMEA on
    # 39 and drives the module's RX on 38. Heltec's net names are
    # direction-ambiguous and several references have this backwards.
    assert "GPSSerial.begin(9600, SERIAL_8N1, 39, 38);" in cpp
    # standby (wake) and reset both driven HIGH; mute-with-TX-low otherwise
    assert "digitalWrite(40, HIGH);" in cpp
    assert "digitalWrite(42, HIGH);" in cpp
    # Bench-proven V4 FEM recipe (2026-08-28): VFEM+CSD static high, VEXT
    # static low, PA_TX_EN per-transfer via RadioLib's rf switch -- the old
    # static-high [7,2,5,46] drive pinned the PA on and deafened the RX.
    for pin in (7, 2):
        assert f"digitalWrite({pin}, HIGH);" in cpp
    assert "digitalWrite(36, LOW);" in cpp
    assert "radio.setRfSwitchPins(RADIOLIB_NC, 46);" in cpp


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


def test_lorawan_matches_golden(lib):
    from wirestudio.targets.lorawan.codec import generate_codec
    from pathlib import Path

    design = _design("ttgo-t-beam")
    fw = generate_firmware(design, lib)
    codec = generate_codec(design, lib)

    golden_dir = Path(__file__).resolve().parent / "golden"

    assert fw["src/main.cpp"] == (golden_dir / "t-beam.cpp").read_text()
    assert fw["platformio.ini"] == (golden_dir / "t-beam.ini").read_text()
    assert codec == (golden_dir / "t-beam.js").read_text()


def test_synthesized_dht_emits_its_configured_pin(lib):
    """A DHT from a retired `lorawan.dht22` block has no wiring, so the render
    context sets `pin` to None. Jinja's `default()` only fires on *undefined*,
    so the old template fell through to a literal "None" in the C++."""
    src = generate_firmware(
        _design("ttgo-t-beam", dht22={"pin": "GPIO13"}), lib
    )["src/main.cpp"]
    assert "DHT dht(13, DHT22);" in src
    assert "None" not in src


def test_tbeam_powers_its_rails_before_using_them(lib):
    """The T-Beam's LoRa and GPS rails hang off the AXP192. Without the PMIC
    init the board boots and reports setting up LoRaWAN while the radio is
    unpowered -- it never joins, and serial output looks healthy."""
    src = generate_firmware(_design("ttgo-t-beam", dht22={"pin": "GPIO13"}), lib)["src/main.cpp"]
    assert "XPowersLib.h" in src
    assert "enableLDO2" in src and "enableLDO3" in src
    assert src.index("power.begin") < src.index("GPSSerial.begin")


def test_design_flash_size_override_wins_over_board_file(lib):
    # heltec-wifi-lora32-v3 pins 8MB; a design that measured 16MB on its own
    # unit gets the bigger partition table.
    design = _design("heltec-wifi-lora32-v3")
    design.board.flash_size_mb = 16
    ini = generate_firmware(design, lib)["platformio.ini"]
    assert "board_build.flash_size = 16MB" in ini
    assert "board_upload.flash_size = 16MB" in ini
    assert "board_build.partitions = default_16MB.csv" in ini


def test_no_override_uses_board_file_flash_size(lib):
    ini = generate_firmware(_design("heltec-wifi-lora32-v3"), lib)["platformio.ini"]
    assert "board_build.flash_size = 8MB" in ini
    assert "board_build.partitions = default_8MB.csv" in ini


def test_ci_component_designs_carry_every_lorawan_block(lib):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_lorawan_firmware", Path(__file__).resolve().parent.parent / "scripts" / "build_lorawan_firmware.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    designs = script.component_designs(lib)
    built = {c.library_id for d in designs for c in d.components}
    board_built = {"axp192", "battery_adc"}  # reported by the boards themselves
    assert built | board_built == {c.id for c in lib.list_components() if c.lorawan is not None}
    for design in designs:
        main = generate_firmware(design, lib)["src/main.cpp"]
        for field in fields_for(design, lib):
            assert field["cpp_expr"] in main


def test_i2c_sensor_blocks_bring_up_wire_and_report_scaled_fields(lib):
    design = _design_with("bme280", "sht4x")
    names = [f["name"] for f in fields_for(design, lib)]
    assert {"bme280_temp_c", "bme280_humidity", "bme280_pressure", "sht4x_temp_c"} <= set(names)
    main = generate_firmware(design, lib)["src/main.cpp"]
    assert "Wire.begin(" in main
    assert "bme280Ok = bme280.begin(0x76, &Wire);" in main
    assert "(int16_t)(bme280TempC * 100.0)" in main


def _wired(components, buses, connections) -> Design:
    return Design.model_validate({
        "schema_version": "1.0", "id": "dev1", "name": "Dev 1", "target": "lorawan", "lorawan": {},
        "board": {"library_id": "ttgo-lora32-v2", "mcu": "esp32"},
        "power": {"supply": "usb", "rail_voltage_v": 3.3},
        "components": [{"id": i, "library_id": c, "label": i, "params": p} for i, c, p in components],
        "buses": buses,
        "connections": [{"component_id": c, "pin_role": r, "target": t} for c, r, t in connections],
    })


def _uart(bus_id, rx, tx, baud=9600):
    return {"id": bus_id, "type": "uart", "rx": rx, "tx": tx, "baud_rate": baud}


def _on(bus_id):
    return {"kind": "bus", "bus_id": bus_id}


def test_each_uart_bus_gets_its_own_hardware_uart(lib):
    parts = [("co2", "mhz19", {}), ("pm", "pmsx003", {})]
    buses = [_uart("u1", "GPIO16", "GPIO17"), _uart("u2", "GPIO32", "GPIO33")]
    conns = [("co2", "TX", _on("u1")), ("co2", "RX", _on("u1")), ("pm", "TX", _on("u2")), ("pm", "RX", _on("u2"))]
    main = generate_firmware(_wired(parts, buses, conns), lib)["src/main.cpp"]
    assert "HardwareSerial co2Serial(1);" in main and "HardwareSerial pmSerial(2);" in main
    assert "co2Serial.begin(9600, SERIAL_8N1, 16, 17);" in main
    third = _wired(parts + [("radar", "ld2410", {})], buses + [_uart("u3", "GPIO4", "GPIO25", 256000)],
                   conns + [("radar", "TX", _on("u3")), ("radar", "RX", _on("u3"))])
    with pytest.raises(ValueError, match="hardware UART"):
        generate_firmware(third, lib)


def test_a_uart_bus_keeps_its_parity(lib):
    design = _wired([("plug", "cse7766", {})], [{**_uart("u1", "GPIO16", "GPIO17", 4800), "parity": "EVEN"}],
                    [("plug", "TX", _on("u1"))])
    assert "plugSerial.begin(4800, SERIAL_8E1, 16, 17);" in generate_firmware(design, lib)["src/main.cpp"]


def test_spi_parts_share_the_radio_bus(lib):
    spi = lib.board("ttgo-lora32-v2").default_buses["spi"]
    conns = [("tc", "CLK", _on("s")), ("tc", "MISO", _on("s")), ("tc", "CS", {"kind": "gpio", "pin": "GPIO25"})]
    main = generate_firmware(_wired([("tc", "max31855", {})], [{"id": "s", "type": "spi", **spi}], conns),
                             lib)["src/main.cpp"]
    assert "#include <SPI.h>" in main and "SPI.begin(5, 19, 27);" in main
    elsewhere = {"id": "s", "type": "spi", "clk": "GPIO14", "miso": "GPIO12", "mosi": "GPIO13"}
    with pytest.raises(ValueError, match="radio's bus"):
        generate_firmware(_wired([("tc", "max31855", {})], [elsewhere], conns), lib)


def test_parts_on_a_hub_read_through_it_and_name_their_fields(lib):
    spi = lib.board("ttgo-lora32-v2").default_buses["spi"]
    parts = [("adc", "mcp3008", {}), ("ch0", "mcp3008_channel", {"number": 0}),
             ("ch5", "mcp3008_channel", {"number": 5, "reference_voltage": "5.0V"}),
             ("bus", "modbus", {}), ("mains", "pzemac", {"address": 2})]
    conns = [("adc", r, _on("s")) for r in ("CLK", "MOSI", "MISO")] + [
        ("adc", "CS", {"kind": "gpio", "pin": "GPIO2"}),
        ("ch0", "HUB", {"kind": "component", "component_id": "adc"}),
        ("ch5", "HUB", {"kind": "component", "component_id": "adc"}),
        ("bus", "UART", _on("u1")), ("bus", "FLOW", {"kind": "gpio", "pin": "GPIO4"}),
        ("mains", "HUB", {"kind": "component", "component_id": "bus"})]
    design = _wired(parts, [{"id": "s", "type": "spi", **spi}, _uart("u1", "GPIO16", "GPIO17")], conns)
    main = generate_firmware(design, lib)["src/main.cpp"]
    assert "ch5Mv = (uint16_t)(adcRead(5) * 5.0 * 1000.0 / 1023.0 + 0.5);" in main
    assert "busRead(2, 0x04, 0, 10, _d)" in main
    assert "digitalWrite(4, HIGH);  // RS485 driver on" in main
    names = [f["name"] for f in fields_for(design, lib)]
    assert {"ch0_voltage", "ch5_voltage", "mains_voltage", "mains_energy"} <= set(names)
    assert "ch5_voltage" in decode_js(fields_for(design, lib))
