"""Library coverage baseline parity.

The `esphome-config` workflow runs `coverage_matrix.py --strict` as a
no-regression gate. This test mirrors that gate in-process so the same
failure surfaces under `pytest` -- much faster feedback than waiting
for CI when you add a library entry or close a coverage gap.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_coverage_matrix_strict_matches_baseline():
    """`coverage_matrix.py --strict` must exit 0 against the committed
    baseline. If this fails, either a new library entry slipped in
    without an example, or `scripts/coverage_baseline.yaml` lists an
    id that now has one and needs to be removed."""
    result = subprocess.run(
        [sys.executable, "scripts/coverage_matrix.py", "--strict"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"coverage_matrix --strict failed:\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
