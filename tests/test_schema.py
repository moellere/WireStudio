"""`design.schema.json` and the pydantic model describe the same document:
every bundled example validates against both, and the schema's property
set is the model's."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import BaseModel

from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((REPO_ROOT / "wirestudio" / "schema" / "design.schema.json").read_text())
EXAMPLES = sorted((REPO_ROOT / "wirestudio" / "examples").glob("*.json"))


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_every_example_validates_against_schema(path):
    jsonschema.validate(json.loads(path.read_text()), SCHEMA)


def _model_paths(model: type[BaseModel], prefix: str = "") -> set[str]:
    out = set()
    for name, field in model.model_fields.items():
        out.add(prefix + name)
        for sub in _nested_models(field.annotation):
            out |= _model_paths(sub, prefix + name + ".")
    return out


def _nested_models(annotation) -> list[type[BaseModel]]:
    from typing import get_args
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return [m for a in get_args(annotation) for m in _nested_models(a)]


def _schema_paths(node: dict, prefix: str = "") -> set[str]:
    out = set()
    for name, prop in node.get("properties", {}).items():
        out.add(prefix + name)
        for sub in [prop, prop.get("items", {}), *prop.get("oneOf", []), *prop.get("items", {}).get("oneOf", [])]:
            out |= _schema_paths(sub, prefix + name + ".")
    return out


def test_schema_properties_are_the_model_fields():
    assert _schema_paths(SCHEMA) == _model_paths(Design)


def test_schema_version_enum_is_what_migrate_reads():
    from wirestudio.migrate import CURRENT_SCHEMA_VERSION, STEPS
    assert SCHEMA["properties"]["schema_version"]["enum"] == [s.from_version for s in STEPS] + [CURRENT_SCHEMA_VERSION]


def test_board_flash_size_override_is_constrained_to_emittable_sizes():
    design = json.loads((REPO_ROOT / "wirestudio" / "examples" / "garage-motion.json").read_text())

    design["board"]["flash_size_mb"] = 32
    jsonschema.validate(design, SCHEMA)

    # 2MB has no default_2MB.csv partition table; neither generator can name one.
    design["board"]["flash_size_mb"] = 2
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(design, SCHEMA)
