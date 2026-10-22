"""`docs/design-schema.md` is what `scripts/schema_doc.py` produces from
`design.schema.json`, and it names every top-level field."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "schema_doc.py"

spec = importlib.util.spec_from_file_location("schema_doc", SCRIPT)
sd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sd)

SCHEMA = json.loads(sd.SCHEMA_PATH.read_text())


def test_committed_page_matches_the_schema():
    assert sd.DOC_PATH.read_text() == sd.render(SCHEMA), (
        "docs/design-schema.md is stale; run python scripts/schema_doc.py")


def test_every_top_level_field_has_a_row():
    page = sd.DOC_PATH.read_text()
    for key in SCHEMA["properties"]:
        assert f"| `{key}` |" in page


def test_connection_targets_are_listed_by_kind():
    page = sd.DOC_PATH.read_text()
    for kind in ("rail", "gpio", "bus", "expander_pin", "component", "net"):
        assert f"`connections[].target<kind={kind}>.kind`" in page
