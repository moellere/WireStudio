"""Checking and creating library boards at runtime."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.library import Library
from wirestudio.library.board_check import check_board_yaml, create_board

BUNDLED = Path(__file__).resolve().parent.parent / "wirestudio" / "library"
DRAFT = (Path(__file__).resolve().parent / "fixtures" / "boards" / "lolin-s2-mini.yaml").read_text()
DEVKIT = (BUNDLED / "boards" / "esp32-devkitc-v4.yaml").read_text()
C3 = (BUNDLED / "boards" / "esp32-c3-devkitm-1.yaml").read_text()


@pytest.fixture
def lib(tmp_path):
    return Library(BUNDLED, tmp_path / "user")


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(library=Library(BUNDLED, tmp_path / "user")))


def _errors(text: str, lib: Library) -> str:
    return " | ".join(check_board_yaml(text, lib).errors)


def test_every_bundled_board_passes(lib):
    for path in sorted((BUNDLED / "boards").glob("*.yaml")):
        report = check_board_yaml(path.read_text(), lib)
        assert report.ok, (path.stem, report.errors)
        assert report.exists == "bundled"


def test_revision_pins_are_checked(lib):
    v4 = (BUNDLED / "boards" / "heltec-wifi-lora32-v4.yaml").read_text()
    assert check_board_yaml(v4, lib).errors == []
    broken = v4.replace('"4.3": {radio: {txen: GPIO5}}', '"4.3": {radio: {txen: GPIO99}}')
    assert "revisions.4.3.radio.txen: GPIO99 is not in gpio_capabilities" in _errors(broken, lib)
    bad_key = v4.replace('"4.3": {radio: {txen: GPIO5}}', '"4.3": {radio: {pa_pin: GPIO5}}')
    assert "unknown keys ['pa_pin']" in _errors(bad_key, lib)


def test_draft_passes_and_renders_its_onboard_parts(lib):
    report = check_board_yaml(DRAFT, lib)
    assert report.ok, report.errors
    assert report.library_id == "lolin-s2-mini" and report.exists == ""
    assert any("gpio_output, gpio_input" in v for v in report.verified)
    assert any("34.3 x 25.4" in v for v in report.verified)
    assert any("no kicad: block" in w for w in report.warnings)
    assert any("datasheet" in n for n in report.not_checked)


def test_unparseable_and_invalid_files_are_reported(lib):
    assert "not valid YAML" in _errors("id: [", lib)
    assert "top level must be a mapping" in _errors("- a", lib)
    assert "platformio_board" in _errors(DRAFT.replace("platformio_board: lolin_s2_mini\n", ""), lib)
    assert "names the file" in _errors(DRAFT.replace("id: lolin-s2-mini", "id: Lolin S2"), lib)


def test_platform_fields_must_agree(lib):
    assert "not an ESP32 variant" in _errors(DRAFT.replace("chip_variant: esp32s2", "chip_variant: esp32s9"), lib)
    assert "needs mcu esp32" in _errors(DRAFT.replace("mcu: esp32\n", "mcu: esp8266\n"), lib)
    assert "not an ESPHome platform" in _errors(DRAFT.replace("chip_variant: esp32s2", "chip_variant: stm32"), lib)
    assert "framework" in _errors(DRAFT.replace("framework: arduino", "framework: zephyr"), lib)


def test_every_named_pin_must_be_a_gpio(lib):
    errors = _errors(DRAFT.replace("sda: GPIO33", "sda: GPIO34").replace("pin: GPIO15", "pin: GPIO14"), lib)
    assert "default_buses.i2c.sda: GPIO34 is not in gpio_capabilities" in errors
    assert "onboard_peripherals.led.pin: GPIO14 is not in gpio_capabilities" in errors
    assert "no scl pin" in _errors(DRAFT.replace(", scl: GPIO35", ""), lib)
    assert "unknown bus type" in _errors(DRAFT.replace("  spi: {", "  qspi: {"), lib)
    assert "no GND rail" in _errors(DRAFT.replace('  - {name: "GND", voltage: 0.0}\n', ""), lib)


def test_an_input_only_pin_cannot_drive_a_bus_line(lib):
    text = DRAFT.replace("GPIO33: [gpio, pwm, i2c_sda]", "GPIO33: [gpio, input_only]")
    assert "GPIO33 is input_only and cannot drive sda" in _errors(text, lib)


def test_radio_pins_are_cross_checked(lib):
    heltec = (BUNDLED / "boards" / "heltec-wifi-lora32-v2.yaml").read_text()
    assert check_board_yaml(heltec, lib).ok
    broken = heltec.replace("pins: {cs: GPIO18", "pins: {cs: GPIO99")
    assert broken != heltec
    assert "radio.pins.cs: GPIO99" in _errors(broken, lib)


def test_enclosure_geometry_stays_on_the_pcb(lib):
    off = DRAFT.replace("offset_mm: 8.95", "offset_mm: 20.0")
    assert "runs off the 25.4 mm short_a edge" in _errors(off, lib)
    edge = DRAFT.replace("edge: short_a", "edge: top")
    assert "edge 'top'" in _errors(edge, lib)


def test_pin_map_is_checked_against_the_symbol(lib, tmp_path, monkeypatch):
    symdir = tmp_path / "symbols"
    symdir.mkdir()
    pins = " ".join(
        f'(pin passive line (at 0 0 0) (length 2.54) (name "Pin_{n}") (number "{n}"))' for n in range(1, 31))
    (symdir / "Connector_Generic.kicad_sym").write_text(
        '(kicad_symbol_lib (version 20231120) (generator kicad_symbol_editor)'
        f' (symbol "Conn_02x15_Odd_Even" {pins}))')
    monkeypatch.setenv("KICAD8_SYMBOL_DIR", str(symdir))
    report = check_board_yaml(C3, lib)
    assert report.ok, report.errors
    assert any("has every pin_map pin" in v for v in report.verified)

    assert "has no pin '31'" in _errors(C3.replace('GPIO1: "19"', 'GPIO1: "31"'), lib)
    assert "GPIO1 and GPIO0 share pin 17, which would short them" in _errors(C3.replace('GPIO1: "19"', 'GPIO1: "17"'), lib)
    assert "no symbol 'Conn_02x20'" in _errors(C3.replace("Conn_02x15_Odd_Even", "Conn_02x20"), lib)
    assert "symbol library 'RF_Module' not found" in _errors(DEVKIT, lib)


def test_create_saves_into_the_user_library_only(lib, tmp_path):
    report = create_board(DRAFT, lib)
    assert report.ok and report.saved.endswith("user/boards/lolin-s2-mini.yaml")
    assert Path(report.saved).read_text() == DRAFT
    assert lib.board_source("lolin-s2-mini") == "user"
    assert lib.board("lolin-s2-mini").chip_variant == "esp32s2"
    assert "lolin-s2-mini" in [b.id for b in lib.list_boards()]

    again = create_board(DRAFT, lib)
    assert not again.ok and any("already exists" in e for e in again.errors)
    assert create_board(DRAFT, lib, overwrite=True).ok

    bundled = create_board(DEVKIT, lib)
    assert not bundled.ok and any("bundled board" in e for e in bundled.errors)
    assert not (tmp_path / "user" / "boards" / "esp32-devkitc-v4.yaml").exists()

    with pytest.raises(PermissionError):
        lib.delete_board("esp32-devkitc-v4")
    lib.delete_board("lolin-s2-mini")
    assert lib.board_source("lolin-s2-mini") == ""
    with pytest.raises(FileNotFoundError):
        lib.board("lolin-s2-mini")

    assert not create_board(DRAFT, Library(BUNDLED)).ok  # no user dir configured


def test_a_bundled_board_wins_over_a_user_file(lib, tmp_path):
    (tmp_path / "user" / "boards").mkdir(parents=True)
    (tmp_path / "user" / "boards" / "esp32-devkitc-v4.yaml").write_text(DRAFT.replace("lolin-s2-mini", "esp32-devkitc-v4"))
    assert lib.board_source("esp32-devkitc-v4") == "bundled"
    assert lib.board("esp32-devkitc-v4").chip_variant == "esp32"
    assert [b.id for b in lib.list_boards()].count("esp32-devkitc-v4") == 1


def test_user_board_flows_into_a_design(lib):
    from wirestudio.generate.yaml_gen import render_yaml
    from wirestudio.model import Design

    assert create_board(DRAFT, lib).ok
    design = Design.model_validate({
        "schema_version": "0.1", "id": "t", "name": "t",
        "board": {"library_id": "lolin-s2-mini", "mcu": "esp32"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": [{"id": "led", "library_id": "gpio_output", "label": "LED"}],
        "buses": [], "requirements": [], "warnings": [],
        "connections": [
            {"component_id": "led", "pin_role": "OUT", "target": {"kind": "gpio", "pin": "GPIO15"}},
        ],
    })
    rendered = render_yaml(design, lib)
    assert "board: lolin_s2_mini" in rendered and "variant: ESP32S2" in rendered
    assert "pin: GPIO15" in rendered


def test_api_round_trip(client):
    check = client.post("/library/boards/check", json={"yaml": DRAFT})
    assert check.status_code == 200 and check.json()["ok"]

    created = client.post("/library/boards", json={"yaml": DRAFT})
    assert created.status_code == 201 and created.json()["saved"]
    listed = {b["id"]: b for b in client.get("/library/boards").json()}
    assert listed["lolin-s2-mini"]["source"] == "user"
    assert listed["esp32-devkitc-v4"]["source"] == "bundled"
    assert client.get("/library/boards/lolin-s2-mini").json()["chip_variant"] == "esp32s2"
    assert client.get("/library/boards/lolin-s2-mini/yaml").text == DRAFT

    assert client.post("/library/boards", json={"yaml": DRAFT}).status_code == 409
    assert client.post("/library/boards", json={"yaml": DEVKIT}).status_code == 409
    bad = client.post("/library/boards", json={"yaml": DRAFT.replace("pin: GPIO15", "pin: GPIO14")})
    assert bad.status_code == 422 and not bad.json()["ok"]

    assert client.delete("/library/boards/esp32-devkitc-v4").status_code == 409
    assert client.delete("/library/boards/lolin-s2-mini").status_code == 200
    assert client.delete("/library/boards/lolin-s2-mini").status_code == 404
    assert "lolin-s2-mini" not in {b["id"] for b in client.get("/library/boards").json()}


def test_agent_tools(lib):
    from wirestudio.agent.tools import _run_board_check, _run_board_create, _run_board_delete, _run_list_boards

    assert _run_board_check({}, lib, yaml=DRAFT)["ok"]
    assert _run_board_create({}, lib, yaml=DRAFT)["saved"]
    sources = {b["library_id"]: b["source"] for b in _run_list_boards({}, lib)["boards"]}
    assert sources["lolin-s2-mini"] == "user"
    assert _run_board_delete({}, lib, library_id="lolin-s2-mini")["ok"]
    assert not _run_board_delete({}, lib, library_id="esp32-devkitc-v4")["ok"]


def test_platformio_board_is_looked_up_in_esphome(lib):
    pytest.importorskip("esphome")
    assert any("lolin_s2_mini is an ESPHome esp32 board" in v for v in check_board_yaml(DRAFT, lib).verified)
    unknown = check_board_yaml(DRAFT.replace("lolin_s2_mini", "no_such_board"), lib)
    assert unknown.ok and any("not in ESPHome's esp32 board list" in w for w in unknown.warnings)
    assert "is an esp32c3 board in ESPHome, not esp32s2" in _errors(DRAFT.replace("lolin_s2_mini", "esp32-c3-devkitm-1"), lib)
