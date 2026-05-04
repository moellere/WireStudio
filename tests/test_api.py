from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from studio.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "version" in r.json()


def test_list_boards_returns_summaries(client):
    r = client.get("/library/boards")
    assert r.status_code == 200
    boards = r.json()
    ids = {b["id"] for b in boards}
    assert {"esp32-devkitc-v4", "wemos-d1-mini", "nodemcu-32s", "ttgo-lora32-v1"} <= ids
    # Summaries don't carry pin tables.
    for b in boards:
        assert "gpio_capabilities" not in b
        assert "rail_names" in b


def test_get_board_returns_full(client):
    r = client.get("/library/boards/esp32-devkitc-v4")
    assert r.status_code == 200
    b = r.json()
    assert b["mcu"] == "esp32"
    assert "GPIO13" in b["gpio_capabilities"]


def test_get_unknown_board_404(client):
    r = client.get("/library/boards/no-such-board")
    assert r.status_code == 404


def test_list_components_returns_summaries(client):
    r = client.get("/library/components")
    assert r.status_code == 200
    comps = r.json()
    ids = {c["id"] for c in comps}
    assert {"bme280", "ssd1306", "ws2812b", "mcp23017", "rc522"} <= ids
    for c in comps:
        assert "yaml_template" not in c  # full template not in summary
        assert "category" in c


def test_list_components_filtered_by_bus(client):
    r = client.get("/library/components?bus=i2c")
    assert r.status_code == 200
    ids = {c["id"] for c in r.json()}
    assert "bme280" in ids
    assert "ssd1306" in ids
    assert "rc522" not in ids  # rc522 needs spi, not i2c


def test_list_components_filtered_by_category(client):
    r = client.get("/library/components?category=sensor")
    assert r.status_code == 200
    ids = {c["id"] for c in r.json()}
    assert "bme280" in ids
    assert "hc-sr04" in ids
    assert "ws2812b" not in ids  # category=light


def test_get_component_returns_full(client):
    r = client.get("/library/components/bme280")
    assert r.status_code == 200
    c = r.json()
    assert "yaml_template" in c["esphome"]
    assert any(p["role"] == "SDA" for p in c["electrical"]["pins"])


def test_get_unknown_component_404(client):
    r = client.get("/library/components/no-such-thing")
    assert r.status_code == 404


def test_validate_accepts_known_example(client):
    design = json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())
    r = client.post("/design/validate", json=design)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["design_id"] == "garage-motion-v1"
    assert body["component_count"] == 2


def test_validate_rejects_missing_required(client):
    bad = {"schema_version": "0.1", "id": "x", "name": "x"}  # missing board/power
    r = client.post("/design/validate", json=bad)
    assert r.status_code == 422


def test_render_returns_yaml_and_ascii(client):
    design = json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())
    r = client.post("/design/render", json=design)
    assert r.status_code == 200
    body = r.json()
    assert body["yaml"].startswith("esphome:\n  name: garage-motion")
    assert "ESP32-DevKitC-V4" in body["ascii"]


def test_render_matches_cli_golden(client):
    design = json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())
    body = client.post("/design/render", json=design).json()
    expected_yaml = (REPO_ROOT / "tests" / "golden" / "garage-motion.yaml").read_text()
    expected_ascii = (REPO_ROOT / "tests" / "golden" / "garage-motion.txt").read_text().rstrip("\n")
    assert body["yaml"] == expected_yaml
    assert body["ascii"] == expected_ascii


def test_render_unknown_library_id_returns_422(client):
    design = json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())
    design["components"][0]["library_id"] = "nope-not-a-real-component"
    r = client.post("/design/render", json=design)
    assert r.status_code == 422


def test_list_examples(client):
    r = client.get("/examples")
    assert r.status_code == 200
    examples = r.json()
    ids = {e["id"] for e in examples}
    assert {"garage-motion-v1", "awning-control", "ttgo-lora32"} <= ids
    for e in examples:
        assert e["board_library_id"]
        assert e["chip_family"] in {"esp8266", "esp32"}


def test_get_example_returns_design_json(client):
    r = client.get("/examples/garage-motion")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "garage-motion-v1"
    assert body["board"]["library_id"] == "esp32-devkitc-v4"


def test_get_unknown_example_404(client):
    r = client.get("/examples/no-such-example")
    assert r.status_code == 404


def test_openapi_schema_advertises_endpoints(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/health" in paths
    assert "/library/boards" in paths
    assert "/design/render" in paths
    assert "/examples/{example_id}" in paths
