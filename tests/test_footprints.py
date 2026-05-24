"""Footprint coverage + format, without the heavy KiCad-library gate.

`scripts/check_footprints.py` verifies each footprint *exists* in the
KiCad footprint libraries (needs a multi-hundred-MB checkout, so it runs
in CI). These tests are the fast local half: every library component and
board declares a footprint, and it's shaped like a `LIB:NAME` reference.
"""
from __future__ import annotations

from pathlib import Path

import pytest

LIB_ROOT = Path(__file__).resolve().parent.parent / "wirestudio" / "library"


def _ids(subdir: str) -> list[str]:
    return sorted(p.stem for p in (LIB_ROOT / subdir).glob("*.yaml"))


@pytest.mark.parametrize("lib_id", _ids("components"))
def test_component_has_footprint(library, lib_id):
    kicad = library.component(lib_id).kicad
    assert kicad is not None, f"component {lib_id} has no kicad block"
    assert kicad.footprint, f"component {lib_id} has no footprint"
    assert ":" in kicad.footprint, f"{lib_id}: footprint must be LIB:NAME, got {kicad.footprint!r}"


@pytest.mark.parametrize("lib_id", _ids("boards"))
def test_board_has_footprint(library, lib_id):
    kicad = library.board(lib_id).kicad
    assert kicad is not None, f"board {lib_id} has no kicad block"
    assert kicad.footprint, f"board {lib_id} has no footprint"
    assert ":" in kicad.footprint, f"{lib_id}: footprint must be LIB:NAME, got {kicad.footprint!r}"
