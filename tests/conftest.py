from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from studio.library import Library, default_library
from studio.model import Design


def _secret_ctor(loader: yaml.Loader, node: yaml.ScalarNode) -> str:
    return f"!secret {node.value}"


yaml.SafeLoader.add_constructor("!secret", _secret_ctor)
yaml.UnsafeLoader.add_constructor("!secret", _secret_ctor)

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def library() -> Library:
    return default_library()


@pytest.fixture
def garage_motion_design() -> Design:
    path = REPO_ROOT / "examples" / "garage-motion.json"
    return Design.model_validate(json.loads(path.read_text()))


@pytest.fixture
def golden_dir() -> Path:
    return Path(__file__).parent / "golden"
