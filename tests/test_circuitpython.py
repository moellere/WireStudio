from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
import wirestudio.api.circuitpython as C


def test_status_reports_boards_version_and_generic(monkeypatch):
    monkeypatch.setattr(C, "_latest_stable", lambda: "10.2.1")
    client = TestClient(create_app())
    body = client.get("/circuitpython/firmware/status").json()
    assert body["available"] is True
    assert body["version"] == "10.2.1"
    assert "heltec-wifi-lora32-v3" in body["boards"]
    assert "wemos-d1-mini" not in body["boards"]  # esp8266: no CP port
    # V4 flashes the V3 image (same substitution as the PlatformIO key).
    assert "heltec-wifi-lora32-v4" in body["generic"]
    assert body["images"]["heltec-wifi-lora32-v4"] == "heltec_esp32s3_wifi_lora_v3"
    assert "heltec-wifi-lora32-v3" not in body["generic"]


def test_status_degrades_when_release_lookup_unreachable(monkeypatch):
    def boom():
        raise RuntimeError("offline")

    monkeypatch.setattr(C, "_latest_stable", boom)
    client = TestClient(create_app())
    body = client.get("/circuitpython/firmware/status").json()
    assert body["available"] is False
    assert "offline" in body["reason"]


def test_firmware_resolves_image_and_version(monkeypatch):
    fetched = {}

    def fake_fetch(url):
        fetched["url"] = url
        return b"CIRCUIT"

    monkeypatch.setattr(C, "_latest_stable", lambda: "10.2.1")
    monkeypatch.setattr(C, "_fetch_firmware", fake_fetch)
    client = TestClient(create_app())
    r = client.get("/circuitpython/firmware?board=m5stack-atoms3")
    assert r.status_code == 200
    assert r.content == b"CIRCUIT"
    assert r.headers["x-flash-offset"] == "0"
    assert fetched["url"] == (
        f"{C._BIN_BASE}/m5stack_atoms3/en_US/"
        "adafruit-circuitpython-m5stack_atoms3-en_US-10.2.1.bin"
    )


def test_firmware_explicit_version_skips_release_lookup(monkeypatch):
    def boom():
        raise RuntimeError("should not be called")

    monkeypatch.setattr(C, "_latest_stable", boom)
    monkeypatch.setattr(C, "_fetch_firmware", lambda url: b"CIRCUIT")
    client = TestClient(create_app())
    r = client.get("/circuitpython/firmware?board=esp32-devkitc-v4&version=v9.2.8")
    assert r.status_code == 200


def test_firmware_esp8266_board_422():
    client = TestClient(create_app())
    assert client.get("/circuitpython/firmware?board=wemos-d1-mini").status_code == 422


def test_firmware_upstream_failure_502(monkeypatch):
    monkeypatch.setattr(C, "_latest_stable", lambda: "10.2.1")

    def boom(url):
        raise RuntimeError("nope")

    monkeypatch.setattr(C, "_fetch_firmware", boom)
    client = TestClient(create_app())
    r = client.get("/circuitpython/firmware?board=esp32-devkitc-v4")
    assert r.status_code == 502


def test_code_serves_starter_for_board():
    client = TestClient(create_app())
    r = client.get("/circuitpython/code?board=heltec-wifi-lora32-v3")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/x-python")
    body = r.text
    assert "import board" in body
    assert 'find_pin("LED", "IO35"' in body  # onboard LED from the board def
    assert "IO36" in body  # Vext power-up


def test_code_marks_generic_builds():
    client = TestClient(create_app())
    body = client.get("/circuitpython/code?board=heltec-wifi-lora32-v4").text
    assert "no official CircuitPython build" in body
    exact = client.get("/circuitpython/code?board=heltec-wifi-lora32-v3").text
    assert "no official CircuitPython build" not in exact


def test_code_unsupported_board_422():
    client = TestClient(create_app())
    assert client.get("/circuitpython/code?board=wemos-d1-mini").status_code == 422


def test_code_generates_valid_python_for_every_board():
    import ast

    client = TestClient(create_app())
    for board in C._BOARDS:
        r = client.get(f"/circuitpython/code?board={board}")
        assert r.status_code == 200, board
        ast.parse(r.text)


def test_design_code_air_quality_station():
    from wirestudio.generate.circuitpython_gen import generate_code
    from wirestudio.library import default_library
    from wirestudio.model import Design
    import json
    from pathlib import Path

    examples = Path(__file__).resolve().parent.parent / "wirestudio" / "examples"
    design = Design.model_validate(
        json.loads((examples / "air-quality-station.json").read_text())
    )
    out = generate_code(design, default_library())
    code = out["code"]
    assert "i2c_i2c0 = busio.I2C(P(22), P(21))" in code
    assert "adafruit_scd4x.SCD4X(i2c_i2c0)" in code
    assert "adafruit_sht4x" in out["deps"]
    # pmsx003 has no CP driver: warned, and its uart bus is not emitted.
    assert any("pmsx003" in w for w in out["warnings"])
    assert "busio.UART" not in code


def test_design_code_every_example_is_valid_python():
    import ast
    import json
    from pathlib import Path

    from wirestudio.generate.circuitpython_gen import generate_code
    from wirestudio.library import default_library
    from wirestudio.model import Design

    lib = default_library()
    examples = Path(__file__).resolve().parent.parent / "wirestudio" / "examples"
    mapped = 0
    for path in sorted(examples.glob("*.json")):
        design = Design.model_validate(json.loads(path.read_text()))
        out = generate_code(design, lib)
        ast.parse(out["code"])  # generator also parses; double-checked here
        if "# Not generated" not in out["code"]:
            mapped += 1
    assert mapped > 15  # plenty of examples generate with zero gaps


def test_design_code_endpoint():
    import json
    from pathlib import Path

    client = TestClient(create_app())
    examples = Path(__file__).resolve().parent.parent / "wirestudio" / "examples"
    design = json.loads((examples / "access-panel.json").read_text())
    r = client.post("/circuitpython/code", json=design)
    assert r.status_code == 200
    body = r.json()
    assert "PN532_I2C" in body["code"]
    assert "adafruit_pn532" in body["deps"]
    assert any("wiegand" in w for w in body["warnings"])


def test_design_code_endpoint_unknown_board_404():
    import json
    from pathlib import Path

    client = TestClient(create_app())
    examples = Path(__file__).resolve().parent.parent / "wirestudio" / "examples"
    design = json.loads((examples / "access-panel.json").read_text())
    design["board"]["library_id"] = "not-a-board"
    assert client.post("/circuitpython/code", json=design).status_code == 404
