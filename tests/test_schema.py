from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_garage_motion_validates_against_schema():
    schema = json.loads((REPO_ROOT / "wirestudio" / "schema" / "design.schema.json").read_text())
    design = json.loads((REPO_ROOT / "wirestudio" / "examples" / "garage-motion.json").read_text())
    jsonschema.validate(design, schema)


def test_awning_control_validates_against_schema():
    schema = json.loads((REPO_ROOT / "wirestudio" / "schema" / "design.schema.json").read_text())
    design = json.loads((REPO_ROOT / "wirestudio" / "examples" / "awning-control.json").read_text())
    jsonschema.validate(design, schema)


@pytest.mark.parametrize(
    "name",
    [
        "wasserpir", "oled", "bluemotion", "distance-sensor", "securitypanel",
        "rc522", "esp32-audio", "bluesonoff", "wemosgps", "ttgo-lora32",
    ],
)
def test_examples_validate_against_schema(name):
    schema = json.loads((REPO_ROOT / "wirestudio" / "schema" / "design.schema.json").read_text())
    design = json.loads((REPO_ROOT / "wirestudio" / "examples" / f"{name}.json").read_text())
    jsonschema.validate(design, schema)
