"""`scripts/check_upgrade.py` against itself: seeded and verified by this
checkout it passes, and each kind of damage it exists to catch fails it
with a line naming the damage. The `upgrade` workflow runs the real thing,
seeded by the previous release from PyPI."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_upgrade.py"
spec = importlib.util.spec_from_file_location("check_upgrade", SCRIPT)
cu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cu)


@pytest.fixture
def clean_env():
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    saved = dict(os.environ)
    data = tmp_path_factory.mktemp("upgrade") / "data"
    try:
        assert cu.seed(data) == 0
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return data


@pytest.fixture
def data(seeded, tmp_path, clean_env):
    copy = tmp_path / "data"
    shutil.copytree(seeded, copy)
    return copy


def _report(data, tmp_path) -> tuple[int, str]:
    summary = tmp_path / "summary.md"
    code = cu.verify(data, summary)
    return code, summary.read_text()


def test_seed_writes_both_layouts_and_a_manifest(seeded):
    manifest = json.loads((seeded / "manifest.json").read_text())
    assert cu.USER_DESIGN_ID in manifest["designs"]
    assert len(list((seeded / "designs").glob("*.json"))) == len(manifest["designs"])
    assert (seeded / "designs.db").exists() and (seeded / "sessions.db").exists()
    assert (seeded / "library" / "components" / "led_driver_npn.yaml").exists()
    keys = {row.get("library_id") or row.get("mpn") for row in manifest["inventory"]}
    assert {"bme280", "2N3904"} <= keys


def test_seeded_by_this_checkout_it_passes(data, tmp_path):
    code, text = _report(data, tmp_path)
    assert code == 0, text
    assert ": pass" in text


def test_a_design_lost_from_the_store_fails(data, tmp_path):
    (data / "designs" / "garage-motion-v1.json").unlink()
    code, text = _report(data, tmp_path)
    assert code == 1
    assert "- files: garage-motion-v1 not listed" in text


def test_a_design_changed_in_the_store_fails(data, tmp_path):
    path = data / "designs" / "garage-motion-v1.json"
    doc = json.loads(path.read_text())
    next(c for c in doc["components"] if c["id"] == "bme1")["params"]["address"] = "0x77"
    path.write_text(json.dumps(doc))
    code, text = _report(data, tmp_path)
    assert code == 1
    assert "- files: garage-motion-v1 renders differently from its original document" in text


def test_inventory_and_user_library_losses_fail(data, tmp_path):
    (data / "inventory.json").write_text(json.dumps({"schema_version": "0.1", "entries": []}))
    shutil.rmtree(data / "library")
    code, text = _report(data, tmp_path)
    assert code == 1
    assert "- inventory does not read back unchanged" in text
    assert "- user component led_driver_npn is not in the library" in text
    assert f"- files: {cu.USER_DESIGN_ID} does not render" in text


def test_seed_refuses_a_non_empty_directory(tmp_path, clean_env):
    (tmp_path / "x").write_text("")
    with pytest.raises(SystemExit, match="not empty"):
        cu.seed(tmp_path)
