import ast
import json
from pathlib import Path

from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
import wirestudio.api.micropython as M
from wirestudio.generate.micropython_gen import generate_code
from wirestudio.library import default_library
from wirestudio.model import Design

EXAMPLES = Path(__file__).resolve().parent.parent / "wirestudio" / "examples"

PAGE = """
<a href="/resources/firmware/ESP32_GENERIC-20250601-v1.26.0-preview.40.g1a2b3c4d.bin">preview</a>
<a href="/resources/firmware/ESP32_GENERIC-20250415-v1.25.0.bin">v1.25.0</a>
<a href="/resources/firmware/ESP32_GENERIC-20241025-v1.24.1.bin">v1.24.1</a>
<a href="/resources/firmware/ESP32_GENERIC-SPIRAM-20250415-v1.25.0.bin">spiram</a>
<a href="/resources/firmware/ESP32_GENERIC-OTA-20250415-v1.25.0.bin">ota</a>
"""


def test_latest_stable_skips_previews_and_matches_the_variant(monkeypatch):
    monkeypatch.setattr(M, "_fetch_page", lambda board: PAGE)
    assert M.latest_stable("ESP32_GENERIC", None) == (
        "https://micropython.org/resources/firmware/ESP32_GENERIC-20250415-v1.25.0.bin", "1.25.0",
    )
    assert M.latest_stable("ESP32_GENERIC", "SPIRAM")[0].endswith("ESP32_GENERIC-SPIRAM-20250415-v1.25.0.bin")
    try:
        M.latest_stable("ESP32_GENERIC", "FLASH_1M")
    except LookupError as e:
        assert "FLASH_1M" in str(e)
    else:
        raise AssertionError("expected LookupError")


def test_every_board_maps_to_a_port_image():
    lib = default_library()
    for board in lib.list_boards():
        img = M.image_for(board)
        assert img is not None, board.id
    assert M.image_for(lib.board("esp32-devkitc-v4")) == ("ESP32_GENERIC", None, 0x1000)
    assert M.image_for(lib.board("esp32cam-ai-thinker")) == ("ESP32_GENERIC", "SPIRAM", 0x1000)
    assert M.image_for(lib.board("heltec-wifi-lora32-v3")) == ("ESP32_GENERIC_S3", None, 0)
    assert M.image_for(lib.board("esp01_1m")) == ("ESP8266_GENERIC", "FLASH_1M", 0)
    assert M.image_for(lib.board("wemos-d1-mini")) == ("ESP8266_GENERIC", None, 0)


def test_status_lists_boards_images_and_offsets(monkeypatch):
    monkeypatch.setattr(M, "_fetch_page", lambda board: PAGE)
    body = TestClient(create_app()).get("/micropython/firmware/status").json()
    assert body["available"] is True and body["version"] == "1.25.0"
    assert "wemos-d1-mini" in body["boards"]  # unlike CircuitPython, ESP8266 has a port
    assert body["images"]["esp32cam-ai-thinker"] == "ESP32_GENERIC-SPIRAM"
    assert body["offsets"]["esp32-devkitc-v4"] == 0x1000 and body["offsets"]["esp32-c3-supermini"] == 0


def test_status_degrades_when_the_site_is_unreachable(monkeypatch):
    def boom(board):
        raise RuntimeError("offline")
    monkeypatch.setattr(M, "_fetch_page", boom)
    body = TestClient(create_app()).get("/micropython/firmware/status").json()
    assert body["available"] is False and "offline" in body["reason"]


def test_firmware_resolves_url_offset_and_version(monkeypatch):
    fetched = {}
    monkeypatch.setattr(M, "_fetch_page", lambda board: PAGE.replace("ESP32_GENERIC", board))
    monkeypatch.setattr(M, "_fetch_firmware", lambda url: fetched.setdefault("url", url) and b"MPY")
    client = TestClient(create_app())
    r = client.get("/micropython/firmware?board=esp32-devkitc-v4")
    assert r.status_code == 200 and r.content == b"MPY"
    assert r.headers["x-flash-offset"] == "4096" and r.headers["x-firmware-version"] == "1.25.0"
    assert fetched["url"].endswith("/ESP32_GENERIC-20250415-v1.25.0.bin")
    r = client.get("/micropython/firmware?board=heltec-wifi-lora32-v3")
    assert r.headers["x-flash-offset"] == "0" and 'ESP32_GENERIC_S3-20250415' in r.headers["content-disposition"]
    assert client.get("/micropython/firmware?board=not-a-board").status_code == 404


def test_firmware_upstream_failure_502(monkeypatch):
    def boom(board):
        raise RuntimeError("offline")
    monkeypatch.setattr(M, "_fetch_page", boom)
    r = TestClient(create_app()).get("/micropython/firmware?board=esp32-devkitc-v4")
    assert r.status_code == 502 and "offline" in r.json()["detail"]


def test_starter_is_valid_python_for_every_board():
    client = TestClient(create_app())
    for board in default_library().list_boards():
        r = client.get(f"/micropython/code?board={board.id}")
        assert r.status_code == 200, board.id
        ast.parse(r.text)
    v3 = client.get("/micropython/code?board=heltec-wifi-lora32-v3").text
    assert "Vext" in v3 and "SoftI2C(" in v3 and "led = Pin(" in v3


def test_design_code_emits_only_the_buses_mapped_parts_use():
    lib = default_library()
    garage = Design.model_validate(json.loads((EXAMPLES / "garage-motion.json").read_text()))
    code = generate_code(garage, lib)["code"]
    assert "i2c_i2c0 = SoftI2C(scl=Pin(22), sda=Pin(21), freq=400000)" in code
    assert "from machine import Pin, SoftI2C" in code
    assert "bme280.BME280(i2c=i2c_i2c0, address=0x76)" in code
    aqs = Design.model_validate(json.loads((EXAMPLES / "air-quality-station.json").read_text()))
    out = generate_code(aqs, lib)
    assert any("scd4x" in w for w in out["warnings"])  # no MicroPython mapping yet
    assert "SoftI2C(" not in out["code"] and "UART(" not in out["code"]  # nothing mapped rides them
    assert "from machine import Pin\n" in out["code"]


def test_design_code_maps_builtin_drivers_and_deps():
    lib = default_library()
    design = Design.model_validate(json.loads((EXAMPLES / "garage-motion.json").read_text()))
    out = generate_code(design, lib)
    assert "Pin.IN" in out["code"] and ast.parse(out["code"])
    for path in sorted(EXAMPLES.glob("*.json")):
        d = Design.model_validate(json.loads(path.read_text()))
        if any(c.library_id == "bme280" for c in d.components):
            out = generate_code(d, lib)
            assert "github:robert-hh/BME280/bme280_float.py" in out["deps"]
            assert "mip.install('github:robert-hh/BME280/bme280_float.py')" in out["code"]
            break
    else:
        raise AssertionError("no bundled example carries a bme280")


def test_design_code_every_example_is_valid_python():
    lib = default_library()
    mapped = 0
    for path in sorted(EXAMPLES.glob("*.json")):
        design = Design.model_validate(json.loads(path.read_text()))
        out = generate_code(design, lib)
        ast.parse(out["code"])
        if "# Not generated" not in out["code"]:
            mapped += 1
    assert mapped >= 5


def test_design_code_endpoint():
    client = TestClient(create_app())
    design = json.loads((EXAMPLES / "garage-motion.json").read_text())
    r = client.post("/micropython/code", json=design)
    assert r.status_code == 200
    body = r.json()
    assert "while True:" in body["code"] and isinstance(body["deps"], list)
    design["board"]["library_id"] = "not-a-board"
    assert client.post("/micropython/code", json=design).status_code == 404
