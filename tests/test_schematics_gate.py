"""Schematic netlist gate, mirrored into pytest.

The `kicad-schematic` workflow runs `scripts/check_schematics.py` against
real KiCad symbol libraries. This test runs the same gate in-process so
it surfaces under `pytest` when the environment has SKiDL + the symbol
libraries (set KICAD8_SYMBOL_DIR), and skips cleanly otherwise -- the
default dev/test box has neither, and pulling a full KiCad symbol set
into every test run would be wrong.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _symbol_dir() -> str | None:
    for var in ("KICAD8_SYMBOL_DIR", "KICAD9_SYMBOL_DIR", "KICAD7_SYMBOL_DIR",
                "KICAD6_SYMBOL_DIR", "KICAD_SYMBOL_DIR"):
        val = os.environ.get(var)
        if val and Path(val).is_dir():
            return val
    return None


@pytest.mark.skipif(
    importlib.util.find_spec("skidl") is None,
    reason="skidl not installed (pip install --no-deps skidl graphviz simp_sexp)",
)
@pytest.mark.skipif(
    _symbol_dir() is None,
    reason="no KiCad symbol libraries (set KICAD8_SYMBOL_DIR)",
)
def test_every_example_netlists():
    """Every bundled example must build a KiCad netlist with no
    unresolved symbols or pins."""
    import sys
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import check_schematics

    assert check_schematics.main([]) == 0
