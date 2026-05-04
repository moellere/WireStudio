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


def test_render_strict_mode_clean_design_passes(client):
    """A design with no compatibility hits renders normally under strict."""
    design = json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())
    r = client.post("/design/render?strict=true", json=design)
    assert r.status_code == 200
    body = r.json()
    assert body["yaml"].startswith("esphome:")


def test_render_strict_mode_blocks_on_compat_warning(client):
    """A design with a known boot-strap warning (TTGO LoRa32 has one)
    422s with the strict_mode_blocked detail under strict=true, but
    still renders fine in permissive mode."""
    design = json.loads((EXAMPLES_DIR / "ttgo-lora32.json").read_text())

    # Permissive (default) -> 200, warnings travel in the body.
    permissive = client.post("/design/render", json=design)
    assert permissive.status_code == 200
    assert any(
        w["severity"] in ("warn", "error")
        for w in permissive.json()["compatibility_warnings"]
    )

    # Strict -> 422 with the warnings in detail.
    strict = client.post("/design/render?strict=true", json=design)
    assert strict.status_code == 422
    detail = strict.json()["detail"]
    assert detail["error"] == "strict_mode_blocked"
    assert "compatibility issue" in detail["message"]
    assert len(detail["warnings"]) >= 1
    assert all(
        w["severity"] in ("warn", "error") for w in detail["warnings"]
    )


def test_render_strict_mode_ignores_info_severity(client):
    """info-severity entries (like the D1 Mini A0 voltage_limit) should
    NOT trip strict mode -- they're educational, not blocking. We use
    the real bluemotion example which is known to have no warn/error
    entries; if this regresses, the strict test above will fire instead."""
    design = json.loads((EXAMPLES_DIR / "bluemotion.json").read_text())
    permissive = client.post("/design/render", json=design).json()
    severities = {w["severity"] for w in permissive["compatibility_warnings"]}
    assert "warn" not in severities and "error" not in severities, (
        "bluemotion gained a warn/error compat entry; pick a different example "
        "for the info-passes-strict test"
    )
    r = client.post("/design/render?strict=true", json=design)
    assert r.status_code == 200


def test_enclosure_openscad_returns_attachment(client):
    design = json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())
    r = client.post("/design/enclosure/openscad", json=design)
    assert r.status_code == 200
    assert "filename=\"garage-motion-v1.scad\"" in r.headers.get("content-disposition", "")
    body = r.text
    assert "module shell()" in body
    assert "module standoffs()" in body
    assert "board_l = 54.4;" in body          # ESP32 DevKitC dimensions
    assert "// usb_micro on short_a" in body


def test_enclosure_openscad_invalid_design_returns_422(client):
    r = client.post("/design/enclosure/openscad", json={"id": "broken"})
    assert r.status_code == 422


def test_enclosure_openscad_unknown_board_returns_422(client):
    """Boards without enclosure metadata (ESP-01S) raise cleanly."""
    design = json.loads((EXAMPLES_DIR / "bluesonoff.json").read_text())
    r = client.post("/design/enclosure/openscad", json=design)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "esp01_1m" in detail
    assert "no enclosure metadata" in detail


def test_render_missing_bus_returns_422_with_message(client):
    """A design that validates but references a non-existent bus
    (e.g. a freshly-added I2C component before the user adds an i2c bus)
    should 422 with a useful message, not 500."""
    design = json.loads((EXAMPLES_DIR / "wasserpir.json").read_text())
    # Append an I2C-needing component with empty bus_id.
    design["components"].append({
        "id": "bme1", "library_id": "bme280", "label": "Stray BME", "params": {},
    })
    design["connections"].extend([
        {"component_id": "bme1", "pin_role": "VCC", "target": {"kind": "rail", "rail": "3V3"}},
        {"component_id": "bme1", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
        {"component_id": "bme1", "pin_role": "SDA", "target": {"kind": "bus", "bus_id": ""}},
        {"component_id": "bme1", "pin_role": "SCL", "target": {"kind": "bus", "bus_id": ""}},
    ])
    r = client.post("/design/render", json=design)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "bme1" in detail
    assert "bus" in detail.lower()


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
    assert "/library/use_cases" in paths


def test_list_use_cases_returns_sorted_aggregate(client):
    r = client.get("/library/use_cases")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list) and len(rows) > 0

    # Each row has the wire shape we promised.
    for row in rows:
        assert set(row.keys()) == {"use_case", "count", "example_components"}
        assert row["count"] >= 1
        assert len(row["example_components"]) <= 3

    # Sorted by descending count, ties broken alphabetically.
    counts = [r["count"] for r in rows]
    assert counts == sorted(counts, reverse=True)
    by_count: dict[int, list[str]] = {}
    for r0 in rows:
        by_count.setdefault(r0["count"], []).append(r0["use_case"])
    for group in by_count.values():
        assert group == sorted(group)


def test_list_use_cases_includes_known_capabilities(client):
    r = client.get("/library/use_cases").json()
    seen = {row["use_case"] for row in r}
    # Sanity-check a few well-known capabilities from the bundled library.
    # If any of these disappear we want a loud failure here, not a silent
    # gap in the picker.
    assert "motion" in seen
    assert "temperature" in seen
    # The PIR is canonical for "motion" and the BME280 for "temperature";
    # confirm they show up in the example_components for at least one row.
    flat = {(row["use_case"], lib_id) for row in r for lib_id in row["example_components"]}
    assert ("motion", "hc-sr501") in flat
    assert any(uc == "temperature" and lib == "bme280" for uc, lib in flat)
