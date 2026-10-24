"""Routed DRC: kicad-cli's report summarised for people, stored with the
routed board, and served by the API and route_pcb.

kicad-cli itself runs in CI's pcb-route gate, which also checks this path
reports the airwires of an unrouted board; here its JSON comes from a
fixture captured from KiCad 8 on the unrouted garage-motion board."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wirestudio.kicad import drc as drc_mod
from wirestudio.kicad.drc import WAIVED, summarize
from wirestudio.kicad.route import routed_drc

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "drc_unrouted_garage_motion.json").read_text())


def test_summary_leads_with_the_airwires():
    s = summarize(FIXTURE)
    assert s["unconnected"] == 7 and s["ok"] is False
    assert s["groups"][0]["type"] == "unconnected_items"
    first = s["groups"][0]["violations"][0]["items"][0]
    assert first["description"].startswith("Pad ") and first["pos"]["x"] is not None


def test_footprint_inherent_types_are_waived_not_failed():
    s = summarize(FIXTURE)
    drill = next(g for g in s["groups"] if g["type"] == "drill_out_of_range")
    assert drill["waived"] and drill["count"] == 12 and drill["reason"] == WAIVED["drill_out_of_range"]
    assert s["errors"] == 0, "the only errors besides airwires are waived"
    assert [g["waived"] for g in s["groups"]][-1] is True, "waived groups sort last"


def test_a_routed_board_with_a_short_is_not_ok():
    report = {"violations": [{"type": "shorting_items", "severity": "error",
                              "description": "Items shorting two nets", "items": []}],
              "unconnected_items": []}
    s = summarize(report)
    assert s["ok"] is False and s["errors"] == 1 and s["unconnected"] == 0


def test_a_clean_routed_board_is_ok():
    report = {"violations": [{"type": "silk_overlap", "severity": "warning", "description": "x", "items": []}],
              "unconnected_items": []}
    s = summarize(report)
    assert s["ok"] is True and s["warnings"] == 0 and s["waived"] == 1


@pytest.fixture
def slot(tmp_path):
    key = "0123456789abcdef"
    (tmp_path / key).mkdir()
    (tmp_path / key / "routed.kicad_pcb").write_text("(kicad_pcb (segment (net 1)))")
    return tmp_path, key


def test_routed_drc_runs_once_and_is_stored(slot, monkeypatch):
    cache, key = slot
    calls = []
    monkeypatch.setattr(drc_mod, "drc_status", lambda: {"available": True, "reason": None})
    monkeypatch.setattr(drc_mod, "run_drc", lambda text: calls.append(text) or summarize(FIXTURE))
    first = routed_drc(key, cache_dir=cache)
    second = routed_drc(key, cache_dir=cache)
    assert first == second and first["unconnected"] == 7
    assert len(calls) == 1 and (cache / key / "drc.json").is_file()


def test_routed_drc_without_kicad_cli_is_none(slot, monkeypatch):
    cache, key = slot
    monkeypatch.setattr(drc_mod, "drc_status", lambda: {"available": False, "reason": "no"})
    assert routed_drc(key, cache_dir=cache) is None
    assert routed_drc("ffffffffffffffff", cache_dir=cache) is None


def test_the_api_serves_the_routed_drc(slot, monkeypatch):
    from fastapi.testclient import TestClient

    from wirestudio.api.app import create_app

    cache, key = slot
    monkeypatch.setenv("WIRESTUDIO_ROUTE_CACHE", str(cache))
    monkeypatch.setattr(drc_mod, "drc_status", lambda: {"available": True, "reason": None})
    monkeypatch.setattr(drc_mod, "run_drc", lambda text: summarize(FIXTURE))
    app = TestClient(create_app())
    body = app.get(f"/design/kicad/route/{key}/drc").json()
    assert body["unconnected"] == 7 and body["groups"][0]["type"] == "unconnected_items"
    assert app.get("/design/kicad/route/ffffffffffffffff/drc").status_code == 404
    assert app.get("/design/kicad/route/nope/drc").status_code == 422


def test_route_pcb_brief_drops_item_detail():
    from wirestudio.agent.tools import _drc_brief

    brief = _drc_brief(summarize(FIXTURE))
    unconnected = brief["groups"][0]
    assert unconnected == {"type": "unconnected_items", "severity": "error", "count": 7, "waived": False,
                           "examples": ["Missing connection between items"] * 3}
    assert "examples" not in brief["groups"][-1], "waived groups carry counts only"
