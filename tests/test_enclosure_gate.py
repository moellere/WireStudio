"""Enclosure render gate, mirrored into pytest.

The `enclosure-render` workflow runs `scripts/check_enclosures.py`,
rendering every enclosure-capable board's `.scad` through OpenSCAD and
asserting a manifold solid. This runs the same gate in-process when the
`openscad` CLI is present, and skips otherwise -- the default test box
doesn't have it and pulling OpenSCAD into every run would be wrong.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(
    shutil.which("openscad") is None,
    reason="openscad not installed (apt-get install openscad)",
)
def test_every_board_enclosure_renders():
    """Every board with enclosure metadata must render to a non-empty
    manifold solid."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import check_enclosures

    assert check_enclosures.main([]) == 0
