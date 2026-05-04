from __future__ import annotations

import yaml

from studio.generate.yaml_gen import render_yaml
from studio.model import Design


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


def test_rc522_matches_golden(rc522_design, library, golden_dir):
    expected = (golden_dir / "rc522.yaml").read_text()
    assert render_yaml(rc522_design, library) == expected


def test_rc522_spi_block_emitted(rc522_design, library):
    parsed = yaml.unsafe_load(render_yaml(rc522_design, library))
    assert parsed["spi"][0]["clk_pin"] == "D5"
    assert parsed["spi"][0]["miso_pin"] == "D6"
    assert parsed["rc522_spi"]["cs_pin"] == "D8"
    assert parsed["rc522_spi"]["spi_id"] == "spi0"


def test_esp32_audio_matches_golden(esp32_audio_design, library, golden_dir):
    expected = (golden_dir / "esp32-audio.yaml").read_text()
    assert render_yaml(esp32_audio_design, library) == expected


def test_esp32_audio_i2s_bus_emits_singleton(esp32_audio_design, library):
    parsed = yaml.unsafe_load(render_yaml(esp32_audio_design, library))
    # i2s_audio is a singleton (dict, not list of dicts)
    assert isinstance(parsed["i2s_audio"], dict)
    assert parsed["i2s_audio"]["i2s_lrclk_pin"] == "GPIO33"
    assert parsed["i2s_audio"]["i2s_bclk_pin"] == "GPIO25"
    assert parsed["media_player"][0]["dac_type"] == "external"
    assert parsed["media_player"][0]["i2s_dout_pin"] == "GPIO32"


def test_esp32_audio_uses_idf_framework(esp32_audio_design, library):
    parsed = yaml.unsafe_load(render_yaml(esp32_audio_design, library))
    assert parsed["esp32"]["framework"]["type"] == "esp-idf"


def test_bluesonoff_matches_golden(bluesonoff_design, library, golden_dir):
    expected = (golden_dir / "bluesonoff.yaml").read_text()
    assert render_yaml(bluesonoff_design, library) == expected


def test_bluesonoff_targets_esp01_1m(bluesonoff_design, library):
    parsed = yaml.unsafe_load(render_yaml(bluesonoff_design, library))
    assert parsed["esp8266"]["board"] == "esp01_1m"
    assert "framework" not in parsed["esp8266"]


def test_wemosgps_matches_golden(wemosgps_design, library, golden_dir):
    expected = (golden_dir / "wemosgps.yaml").read_text()
    assert render_yaml(wemosgps_design, library) == expected


def test_wemosgps_uart_bus_emitted(wemosgps_design, library):
    parsed = yaml.unsafe_load(render_yaml(wemosgps_design, library))
    uart = parsed["uart"][0]
    assert uart["id"] == "my_uart"
    assert uart["rx_pin"] == "D2"
    assert uart["tx_pin"] == "D1"
    assert uart["baud_rate"] == 9600


def test_wemosgps_gps_sensors_render(wemosgps_design, library):
    parsed = yaml.unsafe_load(render_yaml(wemosgps_design, library))
    gps = parsed["gps"]
    assert gps["uart_id"] == "my_uart"
    assert gps["latitude"]["name"] == "Latitude"
    assert gps["satellites"]["name"] == "Visible Satellites"


def test_ttgo_lora32_matches_golden(ttgo_lora32_design, library, golden_dir):
    expected = (golden_dir / "ttgo-lora32.yaml").read_text()
    assert render_yaml(ttgo_lora32_design, library) == expected


def test_ttgo_lora32_radio_block(ttgo_lora32_design, library):
    parsed = yaml.unsafe_load(render_yaml(ttgo_lora32_design, library))
    radio = parsed["sx127x"]
    assert radio["cs_pin"] == "GPIO18"
    assert radio["rst_pin"] == "GPIO23"
    assert radio["dio0_pin"] == "GPIO26"
    assert radio["spi_id"] == "spi0"
    assert radio["frequency"] == 915000000


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


# ---------------------------------------------------------------------------
# DS18B20 + RCWL-0516 (library expansion)
# ---------------------------------------------------------------------------

def _wemos_d1_mini_skeleton(components: list[dict], connections: list[dict]) -> dict:
    """Minimal-but-valid design.json scaffold the new-component tests build on."""
    base = {
        "schema_version": "0.1",
        "id": "fixture",
        "name": "Fixture",
        "board": {"library_id": "wemos-d1-mini", "mcu": "esp8266"},
        "fleet": {"device_name": "fixture", "tags": []},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": components,
        "buses": [],
        "connections": connections,
        "requirements": [],
        "warnings": [],
    }
    return base


def test_multi_temp_matches_golden(multi_temp_design, library, golden_dir):
    expected = (golden_dir / "multi-temp.yaml").read_text()
    actual = render_yaml(multi_temp_design, library)
    assert actual == expected


def test_ds18b20_renders_dallas_temp_pointing_at_bus(library):
    """A DS18B20 wired to a 1-wire bus emits dallas_temp with one_wire_id
    matching the bus id; the bus block itself comes from yaml_gen's
    bus-rendering loop (the component template no longer contains it)."""
    design_dict = _wemos_d1_mini_skeleton(
        components=[{"id": "temp1", "library_id": "ds18b20", "label": "Temp 1", "params": {}}],
        connections=[
            {"component_id": "temp1", "pin_role": "VCC",  "target": {"kind": "rail", "rail": "3V3"}},
            {"component_id": "temp1", "pin_role": "GND",  "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "temp1", "pin_role": "DATA", "target": {"kind": "bus", "bus_id": "wire0"}},
        ],
    )
    design_dict["buses"] = [{"id": "wire0", "type": "1wire", "pin": "D6"}]
    parsed = yaml.unsafe_load(render_yaml(Design.model_validate(design_dict), library))
    assert parsed["one_wire"] == [{"platform": "gpio", "pin": "D6", "id": "wire0"}]
    sensors = [s for s in parsed.get("sensor") or [] if s.get("platform") == "dallas_temp"]
    assert len(sensors) == 1
    assert sensors[0]["one_wire_id"] == "wire0"
    assert sensors[0]["update_interval"] == "60s"


def test_two_ds18b20_instances_share_a_single_one_wire_bus(library):
    """Two DS18B20s wired to the same 1-wire bus emit a SINGLE one_wire
    block and two dallas_temp sensors pointing at it. This is the
    primary motivation for promoting 1-wire to a real bus type."""
    design_dict = _wemos_d1_mini_skeleton(
        components=[
            {"id": "temp1", "library_id": "ds18b20", "label": "Temp 1",
             "params": {"address": "0x1c0000031edd2a28"}},
            {"id": "temp2", "library_id": "ds18b20", "label": "Temp 2",
             "params": {"address": "0xa20000031e1c2828"}},
        ],
        connections=[
            {"component_id": "temp1", "pin_role": "VCC",  "target": {"kind": "rail", "rail": "3V3"}},
            {"component_id": "temp1", "pin_role": "GND",  "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "temp1", "pin_role": "DATA", "target": {"kind": "bus", "bus_id": "wire0"}},
            {"component_id": "temp2", "pin_role": "VCC",  "target": {"kind": "rail", "rail": "3V3"}},
            {"component_id": "temp2", "pin_role": "GND",  "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "temp2", "pin_role": "DATA", "target": {"kind": "bus", "bus_id": "wire0"}},
        ],
    )
    design_dict["buses"] = [{"id": "wire0", "type": "1wire", "pin": "D6"}]
    parsed = yaml.unsafe_load(render_yaml(Design.model_validate(design_dict), library))
    assert parsed["one_wire"] == [{"platform": "gpio", "pin": "D6", "id": "wire0"}]
    sensors = [s for s in parsed["sensor"] if s.get("platform") == "dallas_temp"]
    assert len(sensors) == 2
    assert {s["one_wire_id"] for s in sensors} == {"wire0"}
    # Each sensor renders its own address.
    assert {s["address"] for s in sensors} == {"0x1c0000031edd2a28", "0xa20000031e1c2828"}


def test_rcwl_0516_renders_motion_binary_sensor(library):
    design_dict = _wemos_d1_mini_skeleton(
        components=[{"id": "radar", "library_id": "rcwl-0516", "label": "Hall radar", "params": {}}],
        connections=[
            {"component_id": "radar", "pin_role": "VCC", "target": {"kind": "rail", "rail": "5V"}},
            {"component_id": "radar", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "radar", "pin_role": "OUT", "target": {"kind": "gpio", "pin": "D7"}},
        ],
    )
    parsed = yaml.unsafe_load(render_yaml(Design.model_validate(design_dict), library))
    bs = parsed["binary_sensor"][0]
    assert bs["platform"] == "gpio"
    assert bs["pin"] == "D7"
    assert bs["name"] == "Hall radar"
    assert bs["device_class"] == "motion"
