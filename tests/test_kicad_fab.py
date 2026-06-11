"""Tests for fab-output export (CPL + BOM + routing status).

BOM is pure and always runs. CPL + routing status reuse the board's placement
plan, so they need the footprint libraries and skip without KICAD8_FOOTPRINT_DIR.
Gerber export needs kicad-cli (validated in CI's pcb-drc env), so it isn't
exercised here.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from wirestudio.kicad.fab import (
    fab_status,
    generate_bom,
    generate_cpl,
    is_routed,
)
from wirestudio.kicad.netlist import assign_refs
from wirestudio.kicad.pcb import generate_kicad_pcb, pcb_status, plan_placements
from wirestudio.library import default_library
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"

libs_required = pytest.mark.skipif(
    not pcb_status()["available"],
    reason="KiCad footprint/symbol libs not configured (KICAD8_FOOTPRINT_DIR / KICAD8_SYMBOL_DIR)",
)


@pytest.fixture
def lib():
    return default_library()


def _design(name: str) -> Design:
    return Design.model_validate(json.loads((EXAMPLES_DIR / f"{name}.json").read_text()))


def _rows(csv_text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(csv_text)))


# ---------------------------------------------------------------------------
# BOM -- pure, always runs
# ---------------------------------------------------------------------------

def test_bom_header_and_board_and_designators(lib):
    rows = _rows(generate_bom(_design("garage-motion"), lib))
    assert rows[0] == ["Comment", "Designator", "Footprint", "JLCPCB Part #"]
    refs = assign_refs(_design("garage-motion"), lib)
    all_desigs = {d for r in rows[1:] for d in r[1].split(",")}
    # The board (M1) and every mapped component appear.
    assert refs["__board__"] in all_desigs
    assert all(refs[c.id] in all_desigs for c in _design("garage-motion").components)
    # Footprints are populated.
    assert all(r[2] for r in rows[1:])


def test_bom_groups_identical_parts(lib):
    """multi-temp wires several identical DS18B20s; they collapse to one BOM
    line with comma-joined designators."""
    rows = _rows(generate_bom(_design("multi-temp"), lib))
    multi = [r for r in rows[1:] if "," in r[1]]
    assert multi, "expected at least one grouped (multi-designator) BOM line"


# ---------------------------------------------------------------------------
# CPL + routing -- need the footprint libraries
# ---------------------------------------------------------------------------

@libs_required
def test_cpl_positions_match_the_board_plan(lib):
    d = _design("garage-motion")
    rows = _rows(generate_cpl(d, lib))
    assert rows[0] == ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"]
    plan = {p.ref: (round(p.cx, 3), round(p.cy, 3)) for p in plan_placements(d, lib, _fp_dir())}
    for ref, mx, my, layer, rot in rows[1:]:
        assert layer == "top" and rot == "0"
        assert (round(float(mx), 3), round(float(my), 3)) == plan[ref]


@libs_required
def test_emitted_board_is_unrouted(lib):
    assert is_routed(generate_kicad_pcb(_design("garage-motion"), lib)) is False


def test_fab_status_shape():
    s = fab_status()
    assert set(s) >= {"bom", "cpl", "gerbers", "kicad_cli", "footprints", "reason"}
    assert s["bom"] is True  # BOM is always available


def _fp_dir() -> Path:
    from wirestudio.kicad.pcb import _resolve_footprint_dir
    return _resolve_footprint_dir()
