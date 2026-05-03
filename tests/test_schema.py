from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_garage_motion_validates_against_schema():
    schema = json.loads((REPO_ROOT / "schema" / "design.schema.json").read_text())
    design = json.loads((REPO_ROOT / "examples" / "garage-motion.json").read_text())
    jsonschema.validate(design, schema)
