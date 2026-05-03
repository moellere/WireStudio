from __future__ import annotations

import yaml

from studio.generate.yaml_gen import render_yaml


def test_garage_motion_matches_golden(garage_motion_design, library, golden_dir):
    expected = (golden_dir / "garage-motion.yaml").read_text()
    actual = render_yaml(garage_motion_design, library)
    assert actual == expected


def test_garage_motion_yaml_is_valid_yaml(garage_motion_design, library):
    text = render_yaml(garage_motion_design, library)
    parsed = yaml.unsafe_load(text)
    assert "esphome" in parsed
    assert parsed["esphome"]["name"] == "garage-motion"
    assert parsed["esp32"]["board"] == "esp32dev"


def test_i2c_bus_emitted(garage_motion_design, library):
    parsed = yaml.unsafe_load(render_yaml(garage_motion_design, library))
    assert parsed["i2c"][0]["sda"] == "GPIO21"
    assert parsed["i2c"][0]["scl"] == "GPIO22"
    assert parsed["i2c"][0]["frequency"] == "100kHz"


def test_pir_binary_sensor_pin(garage_motion_design, library):
    parsed = yaml.unsafe_load(render_yaml(garage_motion_design, library))
    assert parsed["binary_sensor"][0]["pin"] == "GPIO13"
    assert parsed["binary_sensor"][0]["device_class"] == "motion"


def test_secrets_use_secret_tag(garage_motion_design, library):
    text = render_yaml(garage_motion_design, library)
    assert "!secret api_key" in text
    assert "!secret wifi_ssid" in text
    assert "!secret 'api_key'" not in text
