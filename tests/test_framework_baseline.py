"""`scripts/framework_baseline.yaml` explains every component a framework
cannot use, and `coverage_matrix.py --strict` holds it to that: an
unexplained gap, a stale entry or a reason outside the three kinds fails
the gate. `tests/test_coverage_baseline.py` runs the real gate; this
drives it with edited baselines."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE = REPO_ROOT / "scripts" / "framework_baseline.yaml"
PREFIXES = ("no driver upstream", "no meaning on this framework", "deferred:")


def _strict(framework_baseline: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/coverage_matrix.py", "--strict",
         "--framework-baseline", str(framework_baseline)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )


def test_every_reason_is_one_of_the_three_kinds():
    raw = yaml.safe_load(BASELINE.read_text())
    assert set(raw) == {"circuitpython", "micropython", "tasmota", "lorawan"}
    for fw, entries in raw.items():
        for cid, reason in entries.items():
            assert reason.startswith(PREFIXES), (fw, cid, reason)
            assert len(reason) > 25, (fw, cid, "a reason, not a label")


def test_an_unexplained_gap_fails(tmp_path):
    raw = yaml.safe_load(BASELINE.read_text())
    dropped = sorted(raw["micropython"])[0]
    del raw["micropython"][dropped]
    edited = tmp_path / "fb.yaml"
    edited.write_text(yaml.safe_dump(raw))
    result = _strict(edited)
    assert result.returncode == 1
    assert "micropython: components without a block and no entry" in result.stderr
    assert dropped in result.stderr


def test_a_stale_entry_and_a_bad_reason_fail(tmp_path):
    raw = yaml.safe_load(BASELINE.read_text())
    raw["circuitpython"]["bme280"] = "deferred: it has a block, so this is stale"
    raw["tasmota"]["hbridge"] = "someone will do it"
    edited = tmp_path / "fb.yaml"
    edited.write_text(yaml.safe_dump(raw))
    result = _strict(edited)
    assert result.returncode == 1
    assert "circuitpython: baseline entries whose component now has a block" in result.stderr
    assert "bme280" in result.stderr
    assert "tasmota: reasons must start with" in result.stderr
    assert "hbridge" in result.stderr
