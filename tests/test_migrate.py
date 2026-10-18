"""`wirestudio.migrate`: the chain that brings a design.json to the current
schema version, and the boundaries that run it. Regenerate the golden with

    python -m wirestudio.migrate tests/fixtures/lorawan-sugar-0.1.json \\
        > tests/golden/lorawan-sugar.migrated.json
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.designs.store import FileDesignStore, SqliteDesignStore
from wirestudio.library import default_library
from wirestudio.migrate import (
    CURRENT_SCHEMA_VERSION,
    STEPS,
    MigrationError,
    main,
    migrate,
    needs_migration,
)
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = sorted((REPO_ROOT / "wirestudio" / "examples").glob("*.json"))
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "lorawan-sugar-0.1.json"
GOLDEN = REPO_ROOT / "tests" / "golden" / "lorawan-sugar.migrated.json"


@pytest.fixture
def sugar() -> dict:
    return json.loads(FIXTURE.read_text())


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------

def test_steps_form_a_chain_to_the_current_version():
    version = STEPS[0].from_version
    for step in STEPS:
        assert step.from_version == version
        version = step.to_version
    assert version == CURRENT_SCHEMA_VERSION


def test_sugar_design_matches_the_golden(sugar):
    result = migrate(sugar)
    assert result.applied == ["lower_lorawan_sugar"]
    assert (result.from_version, result.to_version) == ("0.1", CURRENT_SCHEMA_VERSION)
    assert result.document == json.loads(GOLDEN.read_text())
    assert sugar["schema_version"] == "0.1" and sugar["lorawan"]["gps"], "input left alone"


def test_migrated_document_validates_and_keeps_the_rest_verbatim(sugar):
    doc = migrate(sugar).document
    Design.model_validate(doc)
    for key in ("id", "name", "description", "board", "power", "fleet"):
        assert doc.get(key) == sugar.get(key)
    assert doc["components"][0] == sugar["components"][0]
    assert doc["connections"][0] == sugar["connections"][0]
    assert {c["library_id"] for c in doc["components"][1:]} == {"uart_gps", "dht", "ssd1306"}
    assert set(doc["lorawan"]) == {"region", "sub_band", "provisioning"}


def test_a_0_1_design_without_sugar_only_changes_its_version():
    raw = json.loads(EXAMPLES[0].read_text())
    raw["schema_version"] = "0.1"
    result = migrate(raw)
    assert result.document == {**raw, "schema_version": CURRENT_SCHEMA_VERSION}


def test_current_document_is_returned_as_is():
    raw = json.loads(EXAMPLES[0].read_text())
    result = migrate(raw)
    assert result.document is raw and not result.changed and result.applied == []


@pytest.mark.parametrize("raw,text", [
    ({"id": "x"}, "no schema_version"),
    ({"schema_version": ""}, "no schema_version"),
    ({"schema_version": "9.0"}, "newer release"),
    ([], "JSON object"),
])
def test_unreadable_documents_are_refused(raw, text):
    with pytest.raises(MigrationError, match=text):
        migrate(raw)


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_every_bundled_example_is_current(path):
    raw = json.loads(path.read_text())
    assert not needs_migration(raw)
    assert migrate(raw).document is raw


# ---------------------------------------------------------------------------
# The boundaries that run it
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("make_store", [
    lambda tmp: FileDesignStore(root=tmp),
    lambda tmp: SqliteDesignStore(tmp / "designs.db"),
], ids=["file", "sqlite"])
def test_stores_migrate_on_load(tmp_path, sugar, make_store):
    store = make_store(tmp_path)
    store.save(sugar)
    loaded = store.load("field-node")
    assert loaded["schema_version"] == CURRENT_SCHEMA_VERSION
    assert "gps" not in loaded["lorawan"]
    assert any(c["library_id"] == "uart_gps" for c in loaded["components"])


def test_rest_accepts_and_stores_an_old_document(tmp_path, sugar):
    app = create_app(designs=FileDesignStore(root=tmp_path))
    client = TestClient(app)
    assert client.post("/design/validate", json=sugar).status_code == 200
    r = client.post("/designs", json={"design": sugar})
    assert r.status_code == 200, r.text
    on_disk = json.loads((tmp_path / "field-node.json").read_text())
    assert on_disk["schema_version"] == CURRENT_SCHEMA_VERSION
    assert client.get("/designs/field-node").json()["lorawan"] == on_disk["lorawan"]
    bad = {**sugar, "schema_version": "9.0"}
    assert client.post("/design/validate", json=bad).status_code == 422
    assert "newer release" in client.post("/designs", json={"design": bad}).text


def test_mcp_create_design_stores_the_migrated_document(tmp_path, sugar):
    from wirestudio.mcp.server import _run_set_connection  # noqa: F401  (module import check)
    from wirestudio.designs.active import ActiveDesignTracker
    from wirestudio.mcp.server import build_mcp_server

    store = FileDesignStore(root=tmp_path)
    server = build_mcp_server(default_library(), store, active=ActiveDesignTracker())
    tool = next(t for t in server._tool_manager.list_tools() if t.name == "create_design")
    out = tool.fn(design=copy.deepcopy(sugar))
    assert out["ok"], out
    assert store.load("field-node")["schema_version"] == CURRENT_SCHEMA_VERSION


def test_cli_check_write_and_print(tmp_path, sugar, capsys):
    path = tmp_path / "d.json"
    path.write_text(json.dumps(sugar))
    assert main(["--check", str(path)]) == 1
    assert main([str(path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["schema_version"] == CURRENT_SCHEMA_VERSION
    assert main(["--write", str(path)]) == 0
    assert json.loads(path.read_text()) == printed
    assert main(["--check", str(path)]) == 0
    path.write_text(json.dumps({"schema_version": "9.0", "id": "x"}))
    assert main(["--check", str(path)]) == 2
