from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.designs.seed import insert_module
from wirestudio.generate.ascii_gen import render_ascii
from wirestudio.library import default_library
from wirestudio.model import Design


def _base_design() -> dict:
    return {
        "schema_version": "0.1", "id": "t", "name": "t",
        "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32", "framework": "arduino"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0},
        "components": [], "buses": [], "connections": [],
    }


# --- library ----------------------------------------------------------------

def test_library_loads_module():
    m = default_library().module("oled-knob-13")
    assert len(m.components) == 5
    assert {c.library_id for c in m.components} == {"ssd1306", "rotary_encoder", "gpio_input"}


def test_list_modules_includes_oled_knob():
    assert "oled-knob-13" in {m.id for m in default_library().list_modules()}


def test_unknown_module_raises():
    with pytest.raises(FileNotFoundError):
        default_library().module("nope")


# --- insert_module ----------------------------------------------------------

def test_insert_module_adds_all_components_with_provenance():
    lib = default_library()
    inst, d = insert_module(_base_design(), lib, lib.module("oled-knob-13"))
    assert len(d["components"]) == 5
    assert all(c["module"]["instance"] == inst for c in d["components"])
    assert all(c["module"]["module_id"] == "oled-knob-13" for c in d["components"])
    disp = next(c for c in d["components"] if c["library_id"] == "ssd1306")
    assert disp["params"]["model"] == "SH1106 128x64"
    assert any(b["type"] == "i2c" for b in d["buses"])  # OLED's bus auto-seeded


def test_insert_module_twice_gives_distinct_instances():
    lib = default_library()
    m = lib.module("oled-knob-13")
    d = _base_design()
    inst1, d = insert_module(d, lib, m)
    inst2, d = insert_module(d, lib, m)
    assert inst1 != inst2
    assert len(d["components"]) == 10
    assert {c["module"]["instance"] for c in d["components"]} == {inst1, inst2}


def test_bom_collapses_module_to_one_line():
    lib = default_library()
    _, d = insert_module(_base_design(), lib, lib.module("oled-knob-13"))
    bom = render_ascii(Design.model_validate(d), lib).split("BOM:")[1]
    # one module line; no individual SH1106 / encoder / button part lines
    assert bom.count("OLED + EC11 encoder combo module") == 1
    assert "SSD1306" not in bom
    assert "rotary encoder" not in bom.lower()


# --- API --------------------------------------------------------------------

@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_api_list_modules(client):
    r = client.get("/library/modules")
    assert r.status_code == 200
    mods = {m["id"]: m for m in r.json()}
    assert mods["oled-knob-13"]["component_count"] == 5


def test_api_get_module(client):
    r = client.get("/library/modules/oled-knob-13")
    assert r.status_code == 200
    assert len(r.json()["components"]) == 5


def test_api_get_module_404(client):
    assert client.get("/library/modules/nope").status_code == 404


def test_api_insert_module(client):
    r = client.post("/design/insert_module?module_id=oled-knob-13", json=_base_design())
    assert r.status_code == 200
    d = r.json()
    assert len(d["components"]) == 5
    assert all(c["module"]["module_id"] == "oled-knob-13" for c in d["components"])


def test_api_insert_module_unknown_404(client):
    r = client.post("/design/insert_module?module_id=nope", json=_base_design())
    assert r.status_code == 404
