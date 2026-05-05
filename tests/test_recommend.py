"""Tests for the deterministic component recommender."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from studio.agent.tools import execute_tool
from studio.api.app import create_app
from studio.library import default_library
from studio.recommend.recommender import Constraints, recommend_components

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"


@pytest.fixture
def lib():
    return default_library()


# ---------------------------------------------------------------------------
# Pure-Python recommender
# ---------------------------------------------------------------------------

def test_motion_query_ranks_pir_first(lib):
    out = recommend_components(lib, "motion detection")
    assert len(out) >= 1
    assert out[0].library_id == "hc-sr501"
    assert "motion" in out[0].rationale


def test_motion_query_surfaces_rcwl_alongside_pir(lib):
    """RCWL-0516 advertises the same use_cases as the PIR but is the
    microwave alternative, so it should appear in the top 3 motion picks."""
    out = recommend_components(lib, "motion")
    ids = [r.library_id for r in out[:3]]
    assert "rcwl-0516" in ids


def test_temperature_query_surfaces_ds18b20(lib):
    """DS18B20 is the canonical 1-wire temp sensor; recommending
    'temperature' must include it (BME280 still wins on 'temperature
    humidity' because it covers both, but DS18B20 should be visible)."""
    out = recommend_components(lib, "temperature")
    ids = [r.library_id for r in out]
    assert "ds18b20" in ids


def test_adc_query_surfaces_ads1115(lib):
    """ADC queries should land on the ADS1115 -- it's the only library
    component carrying the `adc` use_case today."""
    out = recommend_components(lib, "adc")
    ids = [r.library_id for r in out]
    assert ids and ids[0] == "ads1115"


def test_imu_query_surfaces_mpu6050(lib):
    """IMU/accelerometer/gyroscope queries should land on the MPU6050."""
    for q in ("imu", "accelerometer", "gyroscope"):
        out = recommend_components(lib, q)
        ids = [r.library_id for r in out]
        assert "mpu6050" in ids, f"{q!r} did not surface mpu6050; got {ids}"


def test_thermocouple_query_lands_on_max31855(lib):
    out = recommend_components(lib, "thermocouple")
    assert out and out[0].library_id == "max31855"


def test_weight_query_lands_on_hx711(lib):
    out = recommend_components(lib, "weight scale")
    assert out and out[0].library_id == "hx711"


def test_lux_query_lands_on_bh1750(lib):
    # BH1750 outranks TSL2561 because it lists `lux` and `ambient_light` as
    # direct use_cases and is the cheaper / more common pick. TSL2561 still
    # appears in the recommendations -- it's just not the top hit anymore.
    out = recommend_components(lib, "lux ambient light")
    assert out and out[0].library_id == "bh1750"
    assert "tsl2561" in [r.library_id for r in out]


def test_pressure_query_includes_bmp180(lib):
    out = recommend_components(lib, "pressure")
    assert "bmp180" in [r.library_id for r in out]


def test_humidity_query_includes_htu21d(lib):
    out = recommend_components(lib, "humidity")
    assert "htu21d" in [r.library_id for r in out]


def test_temperature_humidity_query_returns_bme280(lib):
    out = recommend_components(lib, "temperature humidity")
    ids = [r.library_id for r in out]
    assert "bme280" in ids


def test_rfid_query_returns_rc522(lib):
    out = recommend_components(lib, "rfid")
    ids = [r.library_id for r in out]
    assert "rc522" in ids


def test_no_match_returns_empty(lib):
    out = recommend_components(lib, "qubit cryostat")
    assert out == []


def test_empty_query_returns_empty(lib):
    assert recommend_components(lib, "") == []
    assert recommend_components(lib, "    ") == []


def test_results_are_ranked_descending_by_score(lib):
    out = recommend_components(lib, "display")
    scores = [r.score for r in out]
    assert scores == sorted(scores, reverse=True)


def test_in_examples_count_matches_corpus(lib):
    out = recommend_components(lib, "display")
    # ssd1306 appears in oled, bluemotion (no, that's neopixel)... at minimum
    # oled, ttgo-lora32, securitypanel(commented out -- actually no). Let's
    # verify it's at least 2 via the actual corpus rather than hard-coding.
    ssd = next(r for r in out if r.library_id == "ssd1306")
    expected_count = sum(
        1 for p in EXAMPLES_DIR.glob("*.json")
        if any(c.get("library_id") == "ssd1306"
               for c in json.loads(p.read_text()).get("components", []))
    )
    assert ssd.in_examples == expected_count


def test_voltage_constraint_drops_incompatible(lib):
    # BME280 is 1.8-3.6V; 5V should drop it.
    out = recommend_components(
        lib, "temperature humidity",
        constraints=Constraints(voltage=5.0),
    )
    ids = [r.library_id for r in out]
    assert "bme280" not in ids


def test_voltage_constraint_keeps_compatible(lib):
    out = recommend_components(
        lib, "temperature humidity",
        constraints=Constraints(voltage=3.3),
    )
    ids = [r.library_id for r in out]
    assert "bme280" in ids


def test_max_current_constraint_drops_high_draw(lib):
    # MAX98357A peaks at 1400mA; constraining to 100mA should drop it.
    out = recommend_components(
        lib, "audio",
        constraints=Constraints(max_current_ma_peak=100),
    )
    ids = [r.library_id for r in out]
    assert "max98357a" not in ids


def test_required_bus_constraint(lib):
    out = recommend_components(
        lib, "expander",
        constraints=Constraints(required_bus="i2c"),
    )
    for r in out:
        assert "i2c" in r.required_components


def test_excluded_categories_constraint(lib):
    out = recommend_components(
        lib, "expander",
        constraints=Constraints(excluded_categories=["io_expander"]),
    )
    ids = [r.library_id for r in out]
    assert "mcp23008" not in ids
    assert "mcp23017" not in ids


def test_limit_caps_results(lib):
    out = recommend_components(lib, "sensor", limit=3)
    assert len(out) <= 3


def test_rationale_includes_match_and_examples(lib):
    out = recommend_components(lib, "motion")
    pir = next(r for r in out if r.library_id == "hc-sr501")
    assert "matched" in pir.rationale
    if pir.in_examples > 0:
        assert "example" in pir.rationale


# ---------------------------------------------------------------------------
# Agent tool
# ---------------------------------------------------------------------------

def test_recommend_tool_returns_matches(lib):
    out, is_error = execute_tool("recommend", {"query": "motion"}, {}, lib)
    assert is_error is False
    body = json.loads(out)
    assert body["ok"] is True
    assert body["query"] == "motion"
    assert any(m["library_id"] == "hc-sr501" for m in body["matches"])


def test_recommend_tool_supports_constraints(lib):
    out, _ = execute_tool(
        "recommend",
        {"query": "audio", "constraints": {"max_current_ma_peak": 100}},
        {}, lib,
    )
    body = json.loads(out)
    ids = [m["library_id"] for m in body["matches"]]
    assert "max98357a" not in ids


def test_recommend_tool_rejects_bad_args(lib):
    # Missing required `query`.
    out, is_error = execute_tool("recommend", {}, {}, lib)
    assert is_error is True


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path) -> TestClient:
    from studio.agent.session import SessionStore
    return TestClient(create_app(sessions=SessionStore(root=tmp_path)))


def test_recommend_endpoint(client):
    r = client.post("/library/recommend", json={"query": "motion detection"})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "motion detection"
    assert any(m["library_id"] == "hc-sr501" for m in body["matches"])


def test_recommend_endpoint_with_constraints(client):
    r = client.post("/library/recommend", json={
        "query": "temperature humidity",
        "constraints": {"voltage": 5.0},
    })
    body = r.json()
    ids = [m["library_id"] for m in body["matches"]]
    assert "bme280" not in ids


def test_recommend_endpoint_in_openapi(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/library/recommend" in paths
    assert "/agent/stream" in paths
