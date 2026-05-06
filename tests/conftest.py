from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from wirestudio.library import Library, default_library
from wirestudio.model import Design


def _secret_ctor(loader: yaml.Loader, node: yaml.ScalarNode) -> str:
    return f"!secret {node.value}"


def _lambda_ctor(loader: yaml.Loader, node: yaml.ScalarNode) -> str:
    return f"!lambda {node.value}"


yaml.SafeLoader.add_constructor("!secret", _secret_ctor)
yaml.UnsafeLoader.add_constructor("!secret", _secret_ctor)
yaml.SafeLoader.add_constructor("!lambda", _lambda_ctor)
yaml.UnsafeLoader.add_constructor("!lambda", _lambda_ctor)

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def library() -> Library:
    return default_library()


@pytest.fixture
def garage_motion_design() -> Design:
    path = REPO_ROOT / "wirestudio" / "examples" / "garage-motion.json"
    return Design.model_validate(json.loads(path.read_text()))


@pytest.fixture
def awning_control_design() -> Design:
    path = REPO_ROOT / "wirestudio" / "examples" / "awning-control.json"
    return Design.model_validate(json.loads(path.read_text()))


@pytest.fixture
def wasserpir_design() -> Design:
    return Design.model_validate(json.loads((REPO_ROOT / "wirestudio" / "examples" / "wasserpir.json").read_text()))


@pytest.fixture
def oled_design() -> Design:
    return Design.model_validate(json.loads((REPO_ROOT / "wirestudio" / "examples" / "oled.json").read_text()))


@pytest.fixture
def bluemotion_design() -> Design:
    return Design.model_validate(json.loads((REPO_ROOT / "wirestudio" / "examples" / "bluemotion.json").read_text()))


@pytest.fixture
def distance_sensor_design() -> Design:
    return Design.model_validate(json.loads((REPO_ROOT / "wirestudio" / "examples" / "distance-sensor.json").read_text()))


@pytest.fixture
def securitypanel_design() -> Design:
    return Design.model_validate(json.loads((REPO_ROOT / "wirestudio" / "examples" / "securitypanel.json").read_text()))


@pytest.fixture
def rc522_design() -> Design:
    return Design.model_validate(json.loads((REPO_ROOT / "wirestudio" / "examples" / "rc522.json").read_text()))


@pytest.fixture
def esp32_audio_design() -> Design:
    return Design.model_validate(json.loads((REPO_ROOT / "wirestudio" / "examples" / "esp32-audio.json").read_text()))


@pytest.fixture
def bluesonoff_design() -> Design:
    return Design.model_validate(json.loads((REPO_ROOT / "wirestudio" / "examples" / "bluesonoff.json").read_text()))


@pytest.fixture
def wemosgps_design() -> Design:
    return Design.model_validate(json.loads((REPO_ROOT / "wirestudio" / "examples" / "wemosgps.json").read_text()))


@pytest.fixture
def ttgo_lora32_design() -> Design:
    return Design.model_validate(json.loads((REPO_ROOT / "wirestudio" / "examples" / "ttgo-lora32.json").read_text()))


@pytest.fixture
def multi_temp_design() -> Design:
    return Design.model_validate(json.loads((REPO_ROOT / "wirestudio" / "examples" / "multi-temp.json").read_text()))


@pytest.fixture
def desk_climate_design() -> Design:
    return Design.model_validate(json.loads((REPO_ROOT / "wirestudio" / "examples" / "desk-climate.json").read_text()))


@pytest.fixture
def golden_dir() -> Path:
    return Path(__file__).parent / "golden"
