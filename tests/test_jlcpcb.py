from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.jlcpcb import (
    BomLine,
    BomReport,
    JlcpcbClient,
    JlcpcbPart,
    JlcpcbUnavailable,
    check_bom,
    jlcpcb_status,
    main,
    report_to_dict,
)
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
GARAGE = REPO_ROOT / "wirestudio" / "examples" / "garage-motion.json"

PART = JlcpcbPart(
    lcsc="C92489", mfr="BME280", package="LGA-8", description="sensor",
    stock=8508, price=2.86, basic=False, preferred=True,
)


class StubClient:
    base_url = "https://stub.example"

    def __init__(self, by_keyword):
        self.by_keyword = by_keyword

    def search(self, keyword, limit=8):
        return self.by_keyword.get(keyword, [])


# --- client -----------------------------------------------------------------

def test_part_from_api_normalises_fields():
    p = JlcpcbPart.from_api(
        {"lcsc": 92489, "mfr": "BME280", "package": "LGA-8",
         "is_basic": True, "is_preferred": False, "stock": 10, "price": 2.5}
    )
    assert p.lcsc == "C92489"
    assert p.basic is True and p.preferred is False
    assert p.stock == 10 and p.price == 2.5


def test_client_search_parses_components():
    def handler(request):
        assert request.url.params["q"] == "bme280"
        return httpx.Response(200, json={"components": [
            {"lcsc": 92489, "mfr": "BME280", "package": "LGA-8",
             "is_basic": False, "is_preferred": True, "stock": 8508, "price": 2.86},
        ]})

    client = JlcpcbClient(transport=httpx.MockTransport(handler))
    parts = client.search("bme280")
    assert len(parts) == 1
    assert parts[0].lcsc == "C92489" and parts[0].stock == 8508


def test_client_search_raises_on_http_error():
    client = JlcpcbClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(JlcpcbUnavailable):
        client.search("bme280")


def test_client_search_raises_on_connection_error():
    def boom(_request):
        raise httpx.ConnectError("no route to host")

    client = JlcpcbClient(transport=httpx.MockTransport(boom))
    with pytest.raises(JlcpcbUnavailable):
        client.search("bme280")


def test_jlcpcb_status_available_and_unavailable():
    up = JlcpcbClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"components": []})))
    assert jlcpcb_status(up)["available"] is True

    down = JlcpcbClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    s = jlcpcb_status(down)
    assert s["available"] is False and s["reason"]


# --- check_bom --------------------------------------------------------------

def test_check_bom_classifies_ok_and_not_found(garage_motion_design, library):
    stub = StubClient({"bme280": [PART], "hc-sr501": []})
    report = check_bom(garage_motion_design, library, client=stub)
    assert report.available is True
    lines = {ln.library_id: ln for ln in report.lines}
    assert lines["bme280"].status == "ok"
    assert lines["bme280"].match.lcsc == "C92489"
    assert lines["hc-sr501"].status == "not_found"
    assert lines["hc-sr501"].match is None
    assert report.summary == {"ok": 1, "out_of_stock": 0, "not_found": 1}


def test_check_bom_flags_zero_stock(garage_motion_design, library):
    zero = JlcpcbPart("C1", "X", "0402", "", 0, 1.0, True, False)
    report = check_bom(garage_motion_design, library,
                       client=StubClient({"bme280": [zero], "hc-sr501": [zero]}))
    assert {ln.status for ln in report.lines} == {"out_of_stock"}


def test_check_bom_groups_instances_by_part(library):
    raw = json.loads(GARAGE.read_text())
    dup = dict(raw["components"][1])
    dup["id"] = "bme2"
    raw["components"].append(dup)
    design = Design.model_validate(raw)

    report = check_bom(design, library,
                       client=StubClient({"bme280": [PART], "hc-sr501": [PART]}))
    bme = next(ln for ln in report.lines if ln.library_id == "bme280")
    assert bme.quantity == 2
    assert len(report.lines) == 2  # two bme280 instances collapse to one line


def test_check_bom_degrades_when_api_down(garage_motion_design, library):
    class Down:
        base_url = "https://stub.example"

        def search(self, keyword, limit=8):
            raise JlcpcbUnavailable("api down")

    report = check_bom(garage_motion_design, library, client=Down())
    assert report.available is False
    assert "api down" in report.reason
    assert report.lines == []


def test_report_to_dict_shape(garage_motion_design, library):
    stub = StubClient({"bme280": [PART], "hc-sr501": []})
    d = report_to_dict(check_bom(garage_motion_design, library, client=stub))
    assert set(d) == {"design_id", "available", "api_url", "reason", "summary", "lines"}
    bme = next(line for line in d["lines"] if line["library_id"] == "bme280")
    assert bme["match"]["lcsc"] == "C92489" and bme["quantity"] == 1
    hc = next(line for line in d["lines"] if line["library_id"] == "hc-sr501")
    assert hc["match"] is None


# --- CLI --------------------------------------------------------------------

def test_main_status(monkeypatch, capsys):
    monkeypatch.setattr(
        "wirestudio.jlcpcb.jlcpcb_status",
        lambda: {"available": True, "api_url": "x", "reason": None},
    )
    assert main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["available"] is True


def test_main_check_json(monkeypatch, capsys):
    report = BomReport(
        design_id="garage-motion", available=True, api_url="x",
        lines=[BomLine("bme280", "BME280", 1, "bme280", "ok", "C92489 — 10 in stock")],
    )
    monkeypatch.setattr("wirestudio.jlcpcb.check_bom", lambda design, lib: report)
    assert main(["check", str(GARAGE), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["lines"][0]["status"] == "ok"


def test_main_check_returns_2_when_unavailable(monkeypatch):
    report = BomReport(design_id="g", available=False, api_url="x", reason="down")
    monkeypatch.setattr("wirestudio.jlcpcb.check_bom", lambda design, lib: report)
    assert main(["check", str(GARAGE)]) == 2


# --- API --------------------------------------------------------------------

def test_api_jlcpcb_status(monkeypatch):
    import wirestudio.api.app as appmod
    monkeypatch.setattr(
        appmod, "jlcpcb_status",
        lambda: {"available": False, "api_url": "x", "reason": "down"},
    )
    r = TestClient(create_app()).get("/design/jlcpcb/status")
    assert r.status_code == 200
    assert r.json()["available"] is False


def test_api_jlcpcb_check(monkeypatch):
    import wirestudio.api.app as appmod
    report = BomReport(
        design_id="garage-motion", available=True, api_url="x",
        lines=[BomLine("bme280", "BME280", 1, "bme280", "ok", "C92489 — 10 in stock")],
    )
    monkeypatch.setattr(appmod, "check_bom", lambda d, lib: report)
    r = TestClient(create_app()).post(
        "/design/jlcpcb/check", json=json.loads(GARAGE.read_text())
    )
    assert r.status_code == 200
    body = r.json()
    assert body["lines"][0]["library_id"] == "bme280"
    assert body["summary"]["ok"] == 1
