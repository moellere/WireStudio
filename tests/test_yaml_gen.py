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


def test_awning_control_matches_golden(awning_control_design, library, golden_dir):
    expected = (golden_dir / "awning-control.yaml").read_text()
    actual = render_yaml(awning_control_design, library)
    assert actual == expected


def test_awning_extras_merge_with_components(awning_control_design, library):
    text = render_yaml(awning_control_design, library)
    parsed = yaml.unsafe_load(text)
    assert parsed["esp8266"]["board"] == "d1_mini"
    assert parsed["mcp23008"][0]["address"] == "0x20"
    assert parsed["mcp23008"][0]["i2c_id"] == "i2c0"
    assert len(parsed["binary_sensor"]) == 4
    assert len(parsed["switch"]) == 3
    assert parsed["cover"][0]["platform"] == "endstop"


def test_awning_address_kept_as_string(awning_control_design, library):
    text = render_yaml(awning_control_design, library)
    assert "address: '0x20'" in text
    assert "address: 32" not in text


def test_esp8266_omits_framework_type(awning_control_design, library):
    text = render_yaml(awning_control_design, library)
    assert "type: arduino" not in text


def test_wasserpir_matches_golden(wasserpir_design, library, golden_dir):
    expected = (golden_dir / "wasserpir.yaml").read_text()
    actual = render_yaml(wasserpir_design, library)
    assert actual == expected


def test_wasserpir_filters_render(wasserpir_design, library):
    text = render_yaml(wasserpir_design, library)
    assert "filters:" in text
    assert "delayed_on: 100ms" in text


def test_oled_matches_golden(oled_design, library, golden_dir):
    expected = (golden_dir / "oled.yaml").read_text()
    actual = render_yaml(oled_design, library)
    assert actual == expected


def test_oled_lambda_renders_as_literal_block(oled_design, library):
    text = render_yaml(oled_design, library)
    assert "lambda: |" in text
    assert "WiFi.localIP()" in text
    assert 'lambda: "it.strftime' not in text


def test_oled_reset_pin_emitted(oled_design, library):
    parsed = yaml.unsafe_load(render_yaml(oled_design, library))
    assert parsed["display"][0]["reset_pin"] == "D0"


def test_bluemotion_matches_golden(bluemotion_design, library, golden_dir):
    expected = (golden_dir / "bluemotion.yaml").read_text()
    actual = render_yaml(bluemotion_design, library)
    assert actual == expected


def test_bluemotion_neopixel_pin_and_method(bluemotion_design, library):
    parsed = yaml.unsafe_load(render_yaml(bluemotion_design, library))
    light = parsed["light"][0]
    assert light["pin"] == "GPIO14"
    assert light["method"] == "BIT_BANG"
    assert light["variant"] == "400KBPS"


def test_bluemotion_on_press_key_order_preserved(bluemotion_design, library):
    text = render_yaml(bluemotion_design, library)
    id_pos = text.find("id: led1\n        brightness")
    assert id_pos != -1, "expected 'id' to come before 'brightness' in light.turn_on"


def test_bluemotion_on_boot_merged_into_esphome_block(bluemotion_design, library):
    parsed = yaml.unsafe_load(render_yaml(bluemotion_design, library))
    assert parsed["esphome"]["name"] == "bluemotion1"
    assert "on_boot" in parsed["esphome"]


def test_distance_sensor_matches_golden(distance_sensor_design, library, golden_dir):
    expected = (golden_dir / "distance-sensor.yaml").read_text()
    actual = render_yaml(distance_sensor_design, library)
    assert actual == expected


def test_distance_sensor_lambda_renders_unquoted(distance_sensor_design, library):
    text = render_yaml(distance_sensor_design, library)
    assert "red: !lambda return (100-x)/100.0;" in text
    assert "'!lambda" not in text


def test_securitypanel_matches_golden(securitypanel_design, library, golden_dir):
    expected = (golden_dir / "securitypanel.yaml").read_text()
    actual = render_yaml(securitypanel_design, library)
    assert actual == expected


def test_securitypanel_expander_pins_render(securitypanel_design, library):
    parsed = yaml.unsafe_load(render_yaml(securitypanel_design, library))
    sensors = parsed["binary_sensor"]
    # All 12 sensors should be on the mcp23017 hub.
    assert len(sensors) == 12
    for s in sensors:
        assert "mcp23017" in s["pin"]
        assert s["pin"]["mcp23017"] == "mcp_hub"
        assert s["pin"]["mode"] == "INPUT"
        assert s["pin"]["inverted"] is True
        assert isinstance(s["pin"]["number"], int)


def test_securitypanel_expander_uses_library_id_as_pin_key(securitypanel_design, library):
    text = render_yaml(securitypanel_design, library)
    assert "mcp23017: mcp_hub" in text
    assert "mcp23xxx" not in text


def test_awning_uses_expander_pins_not_extras(awning_control_design, library):
    parsed = yaml.unsafe_load(render_yaml(awning_control_design, library))
    sensors = parsed["binary_sensor"]
    assert len(sensors) == 4  # closed, open, out_button, in_button
    for s in sensors:
        assert s["pin"]["mcp23008"] == "mcp23008_hub"
    switches = [s for s in parsed["switch"] if s["platform"] == "gpio"]
    assert len(switches) == 2  # awning_power, motor_enable
    for s in switches:
        assert s["pin"]["mcp23008"] == "mcp23008_hub"
