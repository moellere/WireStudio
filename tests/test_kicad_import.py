from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from wirestudio.kicad import importer
from wirestudio.kicad.importer import (
    apply_to_component,
    build_kicad_dict,
    component_pin_roles,
    render_block,
    suggest_pin_map,
)
from wirestudio.kicad.symbol_parser import load_symbols, parse_sexpr, resolve_symbol
from wirestudio.library import KicadSymbolRef, default_library

FIXTURES = Path(__file__).parent / "fixtures"
SENSOR_LIB = FIXTURES / "Sensor.kicad_sym"


# --- s-expression parser ----------------------------------------------------

def test_parse_sexpr_quoted_parens_stay_intact():
    assert parse_sexpr('(prop "a (b) c" d)') == ["prop", "a (b) c", "d"]


def test_parse_sexpr_escapes():
    assert parse_sexpr(r'(v "he said \"hi\"")') == ["v", 'he said "hi"']


def test_load_symbols_reads_pins_and_properties():
    symbols = load_symbols(SENSOR_LIB)
    assert set(symbols) == {"BME280", "BMP280"}
    bme = symbols["BME280"]
    assert bme.pins == [("VDD", "1"), ("GND", "2"), ("SCL", "4"), ("SDA", "5")]
    assert bme.properties["Footprint"].startswith("Package_LGA:Bosch_LGA-8")


def test_resolve_symbol_applies_extends():
    symbols = load_symbols(SENSOR_LIB)
    bmp = resolve_symbol(symbols, "BMP280")
    # own property wins, base pins + footprint inherited
    assert bmp.properties["Value"] == "BMP280"
    assert bmp.properties["Footprint"].startswith("Package_LGA:Bosch_LGA-8")
    assert [p[0] for p in bmp.pins] == ["VDD", "GND", "SCL", "SDA"]


# --- kicad: block construction ---------------------------------------------

def test_build_kicad_dict_validates_against_model():
    symbols = load_symbols(SENSOR_LIB)
    d = build_kicad_dict("Sensor", symbols["BME280"])
    assert d["symbol_lib"] == "Sensor"
    assert d["symbol"] == "BME280"
    assert d["footprint"].startswith("Package_LGA:Bosch_LGA-8")
    KicadSymbolRef.model_validate(d)  # would raise on a bad shape


def test_suggest_pin_map_renames_power_only():
    symbols = load_symbols(SENSOR_LIB)
    # GND/SDA/SCL match the symbol exactly; only VCC needs the VDD rename.
    pin_map = suggest_pin_map(symbols["BME280"], ["VCC", "GND", "SDA", "SCL"])
    assert pin_map == {"VCC": "VDD"}


def test_suggest_pin_map_leaves_unresolved_roles_out():
    symbols = load_symbols(SENSOR_LIB)
    pin_map = suggest_pin_map(symbols["BME280"], ["VCC", "INT", "CS"])
    assert pin_map == {"VCC": "VDD"}  # INT / CS have no symbol pin


def test_render_block_roundtrips_through_yaml():
    symbols = load_symbols(SENSOR_LIB)
    d = build_kicad_dict("Sensor", symbols["BME280"], {"VCC": "VDD"})
    parsed = yaml.safe_load(render_block(d))
    assert parsed["kicad"]["symbol"] == "BME280"
    KicadSymbolRef.model_validate(parsed["kicad"])


# --- splicing into a component file ----------------------------------------

def test_apply_to_component_replaces_existing_block(tmp_path):
    src = default_library().root / "components" / "bme280.yaml"
    comp = tmp_path / "bme280.yaml"
    shutil.copy(src, comp)

    apply_to_component(comp, {"symbol_lib": "Sensor", "symbol": "BMP280"})
    data = yaml.safe_load(comp.read_text())

    assert data["kicad"] == {"symbol_lib": "Sensor", "symbol": "BMP280"}
    # the rest of the hand-written file is untouched
    assert data["id"] == "bme280"
    assert data["electrical"]["pins"][0]["role"] == "VCC"
    assert "yaml_template" in data["esphome"]
    # only one kicad: block, comment preserved
    assert comp.read_text().count("\nkicad:") == 1
    assert "# KiCad symbol mapping" in comp.read_text()


def test_apply_to_component_appends_when_absent(tmp_path):
    comp = tmp_path / "widget.yaml"
    comp.write_text("id: widget\nname: Widget\ncategory: sensor\n")

    apply_to_component(comp, {"symbol_lib": "Device", "symbol": "WIDGET"})
    data = yaml.safe_load(comp.read_text())

    assert data["id"] == "widget"
    assert data["kicad"] == {"symbol_lib": "Device", "symbol": "WIDGET"}


def test_component_pin_roles_reads_electrical_pins():
    comp = default_library().root / "components" / "bme280.yaml"
    assert component_pin_roles(comp) == ["VCC", "GND", "SDA", "SCL"]


# --- CLI --------------------------------------------------------------------

def test_main_default_prints_block(capsys):
    rc = importer.main(["--symbol", "Sensor:BME280", "--symbol-dir", str(FIXTURES)])
    assert rc == 0
    out = capsys.readouterr().out
    block = yaml.safe_load(out)
    assert block["kicad"]["symbol"] == "BME280"


def test_main_unknown_symbol_reports_and_fails(capsys):
    rc = importer.main(["--symbol", "Sensor:NOPE", "--symbol-dir", str(FIXTURES)])
    assert rc == 2
    assert "not in" in capsys.readouterr().err


def test_main_missing_library_fails(capsys):
    rc = importer.main(["--symbol", "Ghost:Thing", "--symbol-dir", str(FIXTURES)])
    assert rc == 2
    assert "could not find Ghost.kicad_sym" in capsys.readouterr().err


def test_main_bad_symbol_spec():
    with pytest.raises(SystemExit):
        importer.main(["--symbol", "NoColon"])


def test_main_into_splices_component(tmp_path, monkeypatch, capsys):
    components = tmp_path / "components"
    components.mkdir()
    src = default_library().root / "components" / "bme280.yaml"
    shutil.copy(src, components / "bme280.yaml")
    monkeypatch.setattr(
        importer, "default_library", lambda: SimpleNamespace(root=tmp_path)
    )

    rc = importer.main([
        "--symbol", "Sensor:BME280",
        "--symbol-dir", str(FIXTURES),
        "--into", "bme280",
    ])
    assert rc == 0

    data = yaml.safe_load((components / "bme280.yaml").read_text())
    assert data["kicad"]["symbol_lib"] == "Sensor"
    assert data["kicad"]["symbol"] == "BME280"
    assert data["kicad"]["pin_map"] == {"VCC": "VDD"}
    assert data["id"] == "bme280"  # rest of the file intact
