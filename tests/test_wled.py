"""The WLED target: `cfg.json`'s hardware section from a solved design,
the runtime tier a stock release image reads at boot. Regenerate a
golden with

    python -m wirestudio.targets.wled wirestudio/examples/<stem>.json \\
        > tests/golden/<stem>.wled.json
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.library import default_library
from wirestudio.model import Design
from wirestudio.targets import get_target
from wirestudio.targets.wled import build_cfg, main

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "wirestudio" / "examples"
GOLDEN = REPO_ROOT / "tests" / "golden"
PINNED = ["atom-matrix", "motion-turns-on-light", "flow-meter"]


def _raw(stem: str) -> dict:
    return json.loads((EXAMPLES / f"{stem}.json").read_text())


def _design(stem: str) -> Design:
    return Design.model_validate(_raw(stem))


@pytest.fixture(scope="module")
def lib():
    return default_library()


@pytest.mark.parametrize("stem", PINNED)
def test_examples_match_their_goldens(lib, stem):
    cfg, _ = build_cfg(_design(stem), lib)
    assert json.dumps(cfg, indent=2) + "\n" == (GOLDEN / f"{stem}.wled.json").read_text()


def test_atom_matrix_is_one_rmt_output_and_a_button(lib):
    cfg, warnings = build_cfg(_design("atom-matrix"), lib)
    hw = cfg["hw"]
    [out] = hw["led"]["ins"]
    assert out["type"] == 30 and out["pin"] == [27] and out["len"] == 25 and out["start"] == 0  # SK6812
    assert hw["led"]["total"] == 25
    [btn] = hw["btn"]["ins"]
    assert btn["type"] == 2 and btn["pin"] == [39]
    assert not any("no WLED mapping" in w for w in warnings)


def test_d1_mini_strip_and_pir_resolve_d_labels(lib):
    cfg, _ = build_cfg(_design("motion-turns-on-light"), lib)
    hw = cfg["hw"]
    [out] = hw["led"]["ins"]
    assert out["pin"] == [5]          # D1
    [btn] = hw["btn"]["ins"]
    assert btn["type"] == 5           # PIR sensor
    assert btn["pin"] == [4]          # D2


def test_apa102_is_a_two_wire_output(lib):
    cfg, _ = build_cfg(_design("flow-meter"), lib)
    out = next(o for o in cfg["hw"]["led"]["ins"] if o["type"] == 51)
    assert len(out["pin"]) == 2
    assert out["order"] == 4          # BGR, the apa102 default


def test_chipset_and_order_params_select_the_bus_type(lib):
    raw = _raw("motion-turns-on-light")
    strip = next(c for c in raw["components"] if c["library_id"] == "ws2812b")
    strip["params"] = {**strip.get("params", {}), "variant": "SK6812", "type": "GRBW", "num_leds": 30}
    cfg, warnings = build_cfg(Design.model_validate(raw), lib)
    [out] = cfg["hw"]["led"]["ins"]
    assert out["type"] == 30 and out["order"] == 0 and out["len"] == 30
    assert warnings == []

    strip["params"]["variant"] = "TM1814"
    strip["params"]["type"] = "XYZ"
    cfg, warnings = build_cfg(Design.model_validate(raw), lib)
    assert cfg["hw"]["led"]["ins"][0]["type"] == 31
    assert any("colour order 'XYZ'" in w for w in warnings)


def test_outputs_chain_their_start_index_and_relay_and_ir_are_single(lib):
    raw = _raw("usbc-led-strip")
    raw["components"] += [
        {"id": "strip2", "library_id": "ws2812b", "label": "S2", "params": {"num_leds": 8}},
        {"id": "r1", "library_id": "gpio_output", "label": "R1", "params": {}},
        {"id": "r2", "library_id": "gpio_output", "label": "R2", "params": {}},
        {"id": "ir", "library_id": "remote_receiver", "label": "IR", "params": {}},
    ]
    raw["connections"] += [
        {"component_id": "strip2", "pin_role": "DIN", "target": {"kind": "gpio", "pin": "GPIO16"}},
        {"component_id": "r1", "pin_role": "OUT", "target": {"kind": "gpio", "pin": "GPIO25"}},
        {"component_id": "r2", "pin_role": "OUT", "target": {"kind": "gpio", "pin": "GPIO26"}},
        {"component_id": "ir", "pin_role": "OUT", "target": {"kind": "gpio", "pin": "GPIO4"}},
    ]
    cfg, warnings = build_cfg(Design.model_validate(raw), lib)
    hw = cfg["hw"]
    first, second = hw["led"]["ins"]
    assert second["start"] == first["len"] and hw["led"]["total"] == first["len"] + 8
    assert hw["relay"] == {"pin": 25, "rev": False, "odrain": False}
    assert hw["ir"] == {"pin": 4, "type": 0, "sel": True}
    assert any("r2" in w and "multi_relay" in w for w in warnings)
    assert any("remote layout" in w for w in warnings)


def test_unwired_and_unmapped_parts_warn(lib):
    raw = _raw("usbc-led-strip")
    raw["components"].append({"id": "arm", "library_id": "servo", "label": "Arm", "params": {}})
    raw["components"].append({"id": "loose", "library_id": "gpio_input", "label": "B", "params": {}})
    cfg, warnings = build_cfg(Design.model_validate(raw), lib)
    assert any("arm (servo): no WLED mapping" in w for w in warnings)
    assert any("loose.IN: not wired" in w for w in warnings)
    assert cfg["hw"]["btn"]["ins"] == []


def test_bus_pins_ride_the_if_section(lib):
    raw = _raw("usbc-led-strip")
    raw["buses"].append({"id": "i2c0", "type": "i2c", "sda": "GPIO21", "scl": "GPIO22"})
    cfg, _ = build_cfg(Design.model_validate(raw), lib)
    assert cfg["hw"]["if"]["i2c-pin"] == [21, 22]


def test_a_chip_without_a_release_image_is_refused(lib):
    raw = _raw("c6-supermini")
    with pytest.raises(ValueError, match="esp32c6"):
        build_cfg(Design.model_validate(raw), lib)


def test_target_registry_boards_components_and_validate(lib):
    target = get_target("wled")
    assert "m5stack-atom-matrix" in target.board_ids(lib)
    assert not any("c6" in b for b in target.board_ids(lib))
    assert set(target.component_ids(lib)) == {
        "ws2812b", "apa102", "esp32_rmt_led_strip", "gpio_input", "hc-sr501",
        "rcwl-0516", "remote_receiver", "gpio_output",
        "bme280", "bmp280", "sht3xd", "ds18b20", "dht", "aht10", "grove-aht20", "bh1750", "vl53l0x",
        "battery_adc", "voltage_divider", "rtttl", "i2s_microphone", "ld2410", "ssd1306", "st7789",
        "rotary_encoder", "mpu6050", "bme680", "adc", "potentiometer",
    }
    files = target.generate(_design("atom-matrix"), lib)
    assert json.loads(files["cfg.json"])["hw"]["led"]["total"] == 25
    assert all(w.code == "wled_unmapped" for w in target.validate(_design("atom-matrix"), lib))


def test_cfg_endpoint_and_cli(capsys):
    client = TestClient(create_app())
    r = client.post("/wled/cfg", json=_raw("atom-matrix"))
    assert r.status_code == 200
    assert r.json()["cfg"]["hw"]["led"]["ins"][0]["pin"] == [27]
    assert client.post("/wled/cfg", json=_raw("c6-supermini")).status_code == 422

    assert main([str(EXAMPLES / "atom-matrix.json")]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["hw"]["led"]["total"] == 25


# ---------------------------------------------------------------------------
# The usermod tier
# ---------------------------------------------------------------------------

from wirestudio.targets import wled_build  # noqa: E402
from wirestudio.targets.wled import WLED_RELEASE, build_platformio_override  # noqa: E402


def test_usermod_example_matches_its_goldens(lib):
    design = _design("wled-sensor-strip")
    cfg, _ = build_cfg(design, lib)
    assert json.dumps(cfg, indent=2) + "\n" == (GOLDEN / "wled-sensor-strip.wled.json").read_text()
    override, warnings = build_platformio_override(design, lib)
    assert override == (GOLDEN / "wled-sensor-strip.wled.ini").read_text()
    assert warnings == []


def test_usermods_ride_cfg_um_and_the_override(lib):
    cfg, _ = build_cfg(_design("wled-sensor-strip"), lib)
    assert cfg["um"]["BME280/BMP280"] == {"enabled": True, "I2CAddress": 0x76}
    assert cfg["um"]["Temperature"] == {"enabled": True, "degC": True, "pin": 4}  # via the 1-wire bus
    assert cfg["hw"]["if"]["i2c-pin"] == [21, 22]
    override, _ = build_platformio_override(_design("wled-sensor-strip"), lib)
    lines = override.splitlines()
    assert lines[0] == f"; wirestudio: wled-sensor-strip on WLED {WLED_RELEASE}"
    assert "extends = env:esp32dev" in lines
    assert "  -D USERMOD_BME280" in lines and "  -D USERMOD_DALLASTEMPERATURE" in lines
    assert "  -D TEMPERATURE_PIN=4" in lines
    assert "  BME280@~3.0.0" in lines and "  paulstoffregen/OneWire@~2.3.8" in lines


def test_a_design_without_usermods_has_no_override(lib):
    assert build_platformio_override(_design("atom-matrix"), lib) == (None, [])
    assert "um" not in build_cfg(_design("atom-matrix"), lib)[0]


def test_dht_sets_its_pin_and_type_defines_and_a_second_sensor_warns(lib):
    raw = _raw("motion-turns-on-light")
    raw["components"] += [
        {"id": "th", "library_id": "dht", "label": "TH", "params": {"model": "DHT11"}},
        {"id": "th2", "library_id": "dht", "label": "TH2", "params": {"model": "DHT22"}},
    ]
    raw["connections"] += [
        {"component_id": "th", "pin_role": "DATA", "target": {"kind": "gpio", "pin": "D5"}},
        {"component_id": "th2", "pin_role": "DATA", "target": {"kind": "gpio", "pin": "D6"}},
    ]
    override, warnings = build_platformio_override(Design.model_validate(raw), lib)
    lines = override.splitlines()
    assert "extends = env:nodemcuv2" in lines
    assert "  -D USERMOD_DHT_PIN=14" in lines and "  -D USERMOD_DHT_DHTTYPE=11" in lines
    assert lines.count("  -D USERMOD_DHT") == 1
    assert any("th2" in w and "compiled in once" in w for w in warnings)


def test_generate_and_validate_carry_the_override(lib):
    target = get_target("wled")
    files = target.generate(_design("wled-sensor-strip"), lib)
    assert set(files) == {"cfg.json", "platformio_override.ini"}
    assert "um" in json.loads(files["cfg.json"])
    assert all(w.code == "wled_unmapped" for w in target.validate(_design("wled-sensor-strip"), lib))
    assert target.build_backend().id == "local-platformio-wled"


def _fake_pio(tmp_path: Path) -> Path:
    script = tmp_path / "pio"
    script.write_text(
        "#!/bin/sh\n"
        "d=$3\n"
        "echo \"building $5 in $d\"\n"
        "mkdir -p \"$d/.pio/build/$5\" && printf 'BIN' > \"$d/.pio/build/$5/firmware.bin\"\n"
    )
    script.chmod(0o755)
    return script


def test_build_runs_pio_on_the_checkout_and_caches_the_artifact(lib, tmp_path, monkeypatch):
    src = tmp_path / f"wled-{WLED_RELEASE}"
    src.mkdir()
    (src / "platformio.ini").write_text("[env:esp32dev]\n")
    monkeypatch.setattr(wled_build, "_pio_cmd", lambda: [str(_fake_pio(tmp_path))])
    monkeypatch.setattr(wled_build, "_merge_factory", lambda *a: False)
    design = _design("wled-sensor-strip")

    events = list(wled_build.compile_firmware_events(design, lib, root=tmp_path, use_cache=False))
    done = events[-1]
    assert done["ok"] and done["cache_hit"] is False and done["env"] == "wirestudio"
    assert any("building wirestudio" in e["data"] for e in events if e["type"] == "log")
    override = (src / "platformio_override.ini").read_text()
    assert override == build_platformio_override(design, lib)[0]
    assert Path(done["bin"]).read_bytes() == b"BIN"

    again = list(wled_build.compile_firmware_events(design, lib, root=tmp_path))
    assert again[-1]["cache_hit"] is True and again[-1]["cache_key"] == done["cache_key"]
    assert wled_build.cache_key(override) == done["cache_key"]


def test_checkout_links_the_headers_the_release_includes_by_the_wrong_case(tmp_path):
    src = tmp_path / f"wled-{WLED_RELEASE}"
    um = src / "usermods" / "BH1750_v2"
    um.mkdir(parents=True)
    tft = src / "usermods" / "ST7789_display"
    tft.mkdir()
    (src / "platformio.ini").write_text("")
    (um / "usermod_bh1750.h").write_text("// bh1750\n")
    (tft / "ST7789_display.h").write_text("// st7789\n")
    assert wled_build.checkout(tmp_path) == src
    assert (um / "usermod_BH1750.h").read_text() == "// bh1750\n"
    assert (tft / "ST7789_Display.h").read_text() == "// st7789\n"
    wled_build.checkout(tmp_path)


def test_build_refuses_a_design_without_usermods_and_reports_a_missing_toolchain(lib, tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="no usermods"):
        list(wled_build.compile_firmware_events(_design("atom-matrix"), lib, root=tmp_path))
    monkeypatch.setattr(wled_build, "_pio_cmd", lambda: None)
    from wirestudio.targets.build_backend import BuildUnavailable
    with pytest.raises(BuildUnavailable):
        list(wled_build.compile_firmware_events(_design("wled-sensor-strip"), lib, root=tmp_path, use_cache=False))


def test_compile_endpoints(monkeypatch):
    client = TestClient(create_app())
    assert "release" in client.get("/wled/compile/status").json()
    r = client.post("/wled/compile", json=_raw("atom-matrix"))
    assert r.status_code == 422 and "no usermods" in r.text
    assert client.get("/wled/firmware/nope").status_code == 404
    body = client.post("/wled/cfg", json=_raw("wled-sensor-strip")).json()
    assert body["platformio_override"].startswith("; wirestudio: wled-sensor-strip")


def test_ci_usermod_designs_carry_every_usermod_once_each():
    import importlib.util

    from wirestudio.targets.wled import build_platformio_override

    lib = default_library()
    spec = importlib.util.spec_from_file_location(
        "build_wled_firmware", Path(__file__).resolve().parent.parent / "scripts" / "build_wled_firmware.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    designs = script.usermod_designs(lib)
    built = sorted(c.library_id for d in designs for c in d.components)
    assert built == sorted(c.id for c in lib.list_components() if c.wled is not None and c.wled.kind == "usermod")
    for design in designs:
        ini, warnings = build_platformio_override(design, lib)
        assert warnings == []
        defines = [line.strip() for line in ini.splitlines() if line.strip().startswith("-D USERMOD_") and "=" not in line]
        assert len(defines) == len(set(defines)) == len(design.components)


def test_aht_usermod_tells_the_aht20_from_the_aht10():
    lib = default_library()
    for cid, sensor_type in (("aht10", 0), ("grove-aht20", 2)):
        assert lib.component(cid).wled.um["SensorType"] == sensor_type


def _usermod_design(components, connections, buses=()):
    return Design.model_validate({
        "schema_version": "1.0", "id": "um", "name": "um",
        "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32"},
        "power": {"supply": "usb", "rail_voltage_v": 3.3},
        "components": [{"id": i, "library_id": c, "label": i, "params": p} for i, c, p in components],
        "buses": list(buses),
        "connections": [{"component_id": c, "pin_role": r, "target": t} for c, r, t in connections],
    })


def test_bus_parts_resolve_their_usermod_pins_through_the_bus(lib):
    spi = {"id": "spi_bus0", "type": "spi", "clk": "GPIO18", "mosi": "GPIO23", "miso": "GPIO19"}
    uart = {"id": "uart_bus0", "type": "uart", "rx": "GPIO16", "tx": "GPIO17", "baud_rate": 256000}
    bus = lambda b: {"kind": "bus", "bus_id": b}
    gpio = lambda p: {"kind": "gpio", "pin": p}
    design = _usermod_design(
        [("tft", "st7789", {"width": 135}), ("radar", "ld2410", {})],
        [("tft", "SCK", bus("spi_bus0")), ("tft", "MOSI", bus("spi_bus0")), ("tft", "CS", gpio("GPIO5")),
         ("tft", "DC", gpio("GPIO27")), ("tft", "RESET", gpio("GPIO26")), ("tft", "BACKLIGHT", gpio("GPIO14")),
         ("radar", "TX", bus("uart_bus0")), ("radar", "RX", bus("uart_bus0"))],
        [spi, uart])
    override, warnings = build_platformio_override(design, lib)
    assert warnings == []
    lines = [l.strip() for l in override.splitlines()]
    assert {"-D TFT_MOSI=23", "-D TFT_SCLK=18", "-D TFT_CS=5", "-D TFT_DC=27", "-D TFT_RST=26", "-D TFT_BL=14",
            "-D TFT_WIDTH=135", "-D TFT_HEIGHT=320", "-D USER_SETUP_LOADED=1", "TFT_eSPI @ 2.5.33"} <= set(lines)
    cfg, cfg_warnings = build_cfg(design, lib)
    assert cfg_warnings == ["no LED output: WLED will boot with its default strip on GPIO2"]
    assert cfg["um"]["LD2410Usermod"] == {"enabled": True, "uart_rx_pin": 16, "uart_tx_pin": 17}
    assert cfg["hw"]["if"]["spi-pin"] == [23, 18, 19]


def test_usermod_settings_and_the_analog_button(lib):
    gpio = lambda p: {"kind": "gpio", "pin": p}
    i2c = {"id": "i2c0", "type": "i2c", "sda": "GPIO21", "scl": "GPIO22"}
    design = _usermod_design(
        [("mic", "i2s_microphone", {"pdm": True}), ("knob", "rotary_encoder", {}), ("cell", "battery_adc", {}),
         ("air", "bme680", {"address": "0x77"}), ("oled", "ssd1306", {"model": "SH1106 128x32"}),
         ("dial", "potentiometer", {}), ("beep", "rtttl", {})],
        [("mic", "DIN", gpio("GPIO32")), ("mic", "WS", gpio("GPIO15")), ("mic", "BCLK", gpio("GPIO14")),
         ("knob", "A", gpio("GPIO25")), ("knob", "B", gpio("GPIO26")), ("cell", "SENSE", gpio("GPIO35")),
         ("air", "SDA", {"kind": "bus", "bus_id": "i2c0"}), ("air", "SCL", {"kind": "bus", "bus_id": "i2c0"}),
         ("oled", "SDA", {"kind": "bus", "bus_id": "i2c0"}), ("oled", "SCL", {"kind": "bus", "bus_id": "i2c0"}),
         ("dial", "WIPER", gpio("GPIO34")), ("beep", "OUT", gpio("GPIO27"))],
        [i2c])
    cfg, _ = build_cfg(design, lib)
    assert cfg["um"]["AudioReactive"] == {"enabled": True}
    assert cfg["um"]["Rotary-Encoder"] == {"enabled": True, "SW-pin": -1, "CLK-pin": 25, "DT-pin": 26}
    assert cfg["um"]["Battery"] == {"interval": 30000, "pin": 35}
    assert cfg["um"]["BME680X"] == {"Enabled": True, "i2C Address": 0x77}
    assert cfg["hw"]["btn"]["ins"] == [{"type": 7, "pin": [34], "macros": [0, 0, 0]}]
    override, warnings = build_platformio_override(design, lib)
    lines = [l.strip() for l in override.splitlines()]
    assert {"-D I2S_SDPIN=32", "-D I2S_WSPIN=15", "-D I2S_CKPIN=14", "-D SR_DMTYPE=5", "-D sqrt_internal=sqrtf",
            "-D ENCODER_CLK_PIN=25", "-D ENCODER_DT_PIN=26", "-D USERMOD_BATTERY_MEASUREMENT_PIN=35",
            "-D USERMOD_BUZZER_PIN=27", "boschsensortec/BSEC Software Library @ ^1.8.1492"} <= set(lines)
    assert [w for w in warnings if "FLD_TYPE" in w] == ["oled: model='SH1106 128x32' has no FLD_TYPE value; usermod default used"]
