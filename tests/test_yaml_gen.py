from __future__ import annotations

import yaml

from wirestudio.generate.yaml_gen import render_yaml
from wirestudio.model import Design


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
    # All 12 sensors should be on the mcp_hub via the unified mcp23xxx key.
    assert len(sensors) == 12
    for s in sensors:
        assert "mcp23xxx" in s["pin"]
        assert s["pin"]["mcp23xxx"] == "mcp_hub"
        assert s["pin"]["mode"] == "INPUT"
        assert s["pin"]["inverted"] is True
        assert isinstance(s["pin"]["number"], int)


def test_securitypanel_expander_uses_unified_mcp23xxx_pin_key(securitypanel_design, library):
    # ESPHome 2024+ accepts only `mcp23xxx:` as the pin discriminator on
    # downstream platforms, regardless of whether the hub is a mcp23008
    # (8-bit) or mcp23017 (16-bit). The pre-fix studio emitted
    # `mcp23017:` here, which `esphome config` rejected.
    text = render_yaml(securitypanel_design, library)
    assert "mcp23xxx: mcp_hub" in text
    assert "mcp23017: mcp_hub" not in text


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


def test_esp32_audio_uses_arduino_framework(esp32_audio_design, library):
    # max98357a's media_player platform is arduino-only in upstream ESPHome
    # (`cv.only_with_arduino`); the example used to set framework=esp-idf,
    # which `esphome config` rejected. Revisit when esp-idf gains the
    # platform or we route audio through speaker: + media_player: speaker
    # chained.
    parsed = yaml.unsafe_load(render_yaml(esp32_audio_design, library))
    assert parsed["esp32"]["framework"]["type"] == "arduino"


def test_bluesonoff_matches_golden(bluesonoff_design, library, golden_dir):
    expected = (golden_dir / "bluesonoff.yaml").read_text()
    assert render_yaml(bluesonoff_design, library) == expected


def test_bluesonoff_targets_esp01_1m(bluesonoff_design, library):
    parsed = yaml.unsafe_load(render_yaml(bluesonoff_design, library))
    assert parsed["esp8266"]["board"] == "esp01_1m"
    assert "framework" not in parsed["esp8266"]


def test_esp32_c3_emits_unified_esp32_block_with_variant(desk_climate_design, library):
    # ESPHome unifies all ESP32 family variants under a single `esp32:`
    # top-level key; the variant goes inline. The pre-fix studio used the
    # board's `chip_variant` (e.g. `esp32c3`) as the top-level key, which
    # `esphome config` rejects with "Platform missing." The fix in
    # build_yaml_dict normalises everything starting with `esp32` to the
    # unified key.
    parsed = yaml.unsafe_load(render_yaml(desk_climate_design, library))
    assert "esp32" in parsed
    assert "esp32c3" not in parsed
    assert parsed["esp32"]["variant"] == "ESP32C3"
    assert parsed["esp32"]["board"] == "esp32-c3-devkitm-1"
    assert parsed["esp32"]["framework"]["type"] == "arduino"


def test_classic_esp32_omits_variant_field(garage_motion_design, library):
    # Default dual-core Xtensa ESP32 doesn't get an explicit `variant:`.
    # Only the C3/S2/S3/C6/H2 variants do.
    parsed = yaml.unsafe_load(render_yaml(garage_motion_design, library))
    assert "variant" not in parsed["esp32"]


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
        # mcp23xxx is the unified pin discriminator (ESPHome 2024+).
        assert s["pin"]["mcp23xxx"] == "mcp23008_hub"
    switches = [s for s in parsed["switch"] if s["platform"] == "gpio"]
    assert len(switches) == 2  # awning_power, motor_enable
    for s in switches:
        assert s["pin"]["mcp23xxx"] == "mcp23008_hub"


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


# ---------------------------------------------------------------------------
# ADS1115 + MPU6050 (library expansion v2)
# ---------------------------------------------------------------------------

def _esp32_with_i2c(components: list[dict], extra_connections: list[dict]) -> dict:
    base = {
        "schema_version": "0.1",
        "id": "i2c-fixture",
        "name": "I2C fixture",
        "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32"},
        "fleet": {"device_name": "i2c-fixture", "tags": []},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": components,
        "buses": [{"id": "i2c0", "type": "i2c", "sda": "GPIO21", "scl": "GPIO22"}],
        "connections": extra_connections,
        "requirements": [],
        "warnings": [],
    }
    return base


def test_ads1115_hub_alone_emits_no_sensors(library):
    """The hub component is hub-only after the split: it registers the
    `ads1115:` block but emits no `sensor:` entries. Channels live in
    separate ads1115_channel components."""
    design_dict = _esp32_with_i2c(
        components=[{"id": "adc1", "library_id": "ads1115", "label": "Hub",
                     "params": {"address": "0x49"}}],
        extra_connections=[
            {"component_id": "adc1", "pin_role": "VCC", "target": {"kind": "rail", "rail": "3V3"}},
            {"component_id": "adc1", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "adc1", "pin_role": "SDA", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "adc1", "pin_role": "SCL", "target": {"kind": "bus", "bus_id": "i2c0"}},
        ],
    )
    parsed = yaml.unsafe_load(render_yaml(Design.model_validate(design_dict), library))
    hub = parsed["ads1115"][0]
    assert hub["id"] == "adc1_hub"
    assert hub["address"] == "0x49"
    assert hub["i2c_id"] == "i2c0"
    assert "sensor" not in parsed or all(
        s.get("platform") != "ads1115" for s in parsed["sensor"]
    )


def test_ads1115_channel_renders_sensor_pointing_at_hub(library):
    """An ads1115_channel with HUB target = component:adc1 emits a
    `sensor:` entry whose ads1115_id matches the hub's `<id>_hub`
    handle. Each channel's params (multiplexer/gain/update_interval)
    flow through independently."""
    design_dict = _esp32_with_i2c(
        components=[
            {"id": "adc1", "library_id": "ads1115", "label": "Hub", "params": {}},
            {"id": "bat",  "library_id": "ads1115_channel", "label": "Battery V",
             "params": {"multiplexer": "A0_GND", "gain": "4.096", "update_interval": "10s"}},
            {"id": "load", "library_id": "ads1115_channel", "label": "Load V",
             "params": {"multiplexer": "A1_GND", "gain": "2.048"}},
        ],
        extra_connections=[
            {"component_id": "adc1", "pin_role": "VCC", "target": {"kind": "rail", "rail": "3V3"}},
            {"component_id": "adc1", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "adc1", "pin_role": "SDA", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "adc1", "pin_role": "SCL", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "bat",  "pin_role": "HUB", "target": {"kind": "component", "component_id": "adc1"}},
            {"component_id": "load", "pin_role": "HUB", "target": {"kind": "component", "component_id": "adc1"}},
        ],
    )
    parsed = yaml.unsafe_load(render_yaml(Design.model_validate(design_dict), library))
    sensors = [s for s in parsed["sensor"] if s.get("platform") == "ads1115"]
    by_name = {s["name"]: s for s in sensors}
    assert set(by_name) == {"Battery V", "Load V"}
    assert by_name["Battery V"]["ads1115_id"] == "adc1_hub"
    assert by_name["Battery V"]["multiplexer"] == "A0_GND"
    # YAML un-quoting parses "4.096" as a float; assert via string equality
    # on the original render.
    assert by_name["Battery V"]["gain"] == 4.096
    assert by_name["Battery V"]["update_interval"] == "10s"
    assert by_name["Load V"]["ads1115_id"] == "adc1_hub"
    assert by_name["Load V"]["update_interval"] == "60s"  # default


def test_ads1115_channel_solver_auto_binds_to_hub(library):
    """An unbound HUB target on an ads1115_channel resolves to the only
    ads1115 hub in the design via the new `kind: component` solve path."""
    from wirestudio.csp.pin_solver import solve_pins
    from wirestudio.library import default_library
    lib = default_library()
    design_dict = _esp32_with_i2c(
        components=[
            {"id": "adc1", "library_id": "ads1115", "label": "Hub", "params": {}},
            {"id": "bat",  "library_id": "ads1115_channel", "label": "Battery V",
             "params": {"multiplexer": "A0_GND"}},
        ],
        extra_connections=[
            {"component_id": "adc1", "pin_role": "VCC", "target": {"kind": "rail", "rail": "3V3"}},
            {"component_id": "adc1", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "adc1", "pin_role": "SDA", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "adc1", "pin_role": "SCL", "target": {"kind": "bus", "bus_id": "i2c0"}},
            # Unbound: solver must fill in component_id.
            {"component_id": "bat",  "pin_role": "HUB", "target": {"kind": "component", "component_id": ""}},
        ],
    )
    result = solve_pins(design_dict, lib)
    bat_conn = next(c for c in result.design["connections"] if c["component_id"] == "bat")
    assert bat_conn["target"] == {"kind": "component", "component_id": "adc1"}


def test_mpu6050_renders_six_axes_plus_die_temp(library):
    design_dict = _esp32_with_i2c(
        components=[{"id": "imu1", "library_id": "mpu6050", "label": "Door tilt", "params": {}}],
        extra_connections=[
            {"component_id": "imu1", "pin_role": "VCC", "target": {"kind": "rail", "rail": "3V3"}},
            {"component_id": "imu1", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "imu1", "pin_role": "SDA", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "imu1", "pin_role": "SCL", "target": {"kind": "bus", "bus_id": "i2c0"}},
        ],
    )
    parsed = yaml.unsafe_load(render_yaml(Design.model_validate(design_dict), library))
    imu = next(s for s in parsed["sensor"] if s.get("platform") == "mpu6050")
    assert imu["address"] == "0x68"
    assert imu["i2c_id"] == "i2c0"
    # Six axes + die temp.
    for ax in ("accel_x", "accel_y", "accel_z", "gyro_x", "gyro_y", "gyro_z"):
        assert ax in imu and imu[ax]["name"].startswith("Door tilt")
    assert imu["temperature"]["name"] == "Door tilt Die Temp"


def test_ads1115_and_mpu6050_share_one_i2c_bus(library):
    """ADS1115 hub + an ADS1115 channel + MPU6050 on the same bus emit
    a single i2c block, single ads1115 hub block, plus channel and
    mpu6050 sensors -- no duplication."""
    design_dict = _esp32_with_i2c(
        components=[
            {"id": "adc1", "library_id": "ads1115", "label": "ADC", "params": {}},
            {"id": "bat",  "library_id": "ads1115_channel", "label": "Bat",
             "params": {"multiplexer": "A0_GND"}},
            {"id": "imu1", "library_id": "mpu6050", "label": "IMU", "params": {}},
        ],
        extra_connections=[
            {"component_id": "adc1", "pin_role": "VCC", "target": {"kind": "rail", "rail": "3V3"}},
            {"component_id": "adc1", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "adc1", "pin_role": "SDA", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "adc1", "pin_role": "SCL", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "bat",  "pin_role": "HUB", "target": {"kind": "component", "component_id": "adc1"}},
            {"component_id": "imu1", "pin_role": "VCC", "target": {"kind": "rail", "rail": "3V3"}},
            {"component_id": "imu1", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "imu1", "pin_role": "SDA", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "imu1", "pin_role": "SCL", "target": {"kind": "bus", "bus_id": "i2c0"}},
        ],
    )
    parsed = yaml.unsafe_load(render_yaml(Design.model_validate(design_dict), library))
    assert len(parsed["i2c"]) == 1
    assert parsed["i2c"][0]["id"] == "i2c0"
    assert len(parsed["ads1115"]) == 1
    sensor_platforms = {s["platform"] for s in parsed["sensor"]}
    assert "ads1115" in sensor_platforms
    assert "mpu6050" in sensor_platforms


# ---------------------------------------------------------------------------
# Library expansion v3: BMP180, HTU21D, MAX31855, HX711, TSL2561
# ---------------------------------------------------------------------------

def _esp32_with_spi(components: list[dict], extra_connections: list[dict]) -> dict:
    return {
        "schema_version": "0.1",
        "id": "spi-fixture",
        "name": "SPI fixture",
        "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32"},
        "fleet": {"device_name": "spi-fixture", "tags": []},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": components,
        "buses": [{"id": "spi0", "type": "spi",
                    "clk": "GPIO18", "miso": "GPIO19", "mosi": "GPIO23"}],
        "connections": extra_connections,
        "requirements": [],
        "warnings": [],
    }


def test_bmp180_renders_temperature_and_pressure(library):
    design_dict = _esp32_with_i2c(
        components=[{"id": "weather", "library_id": "bmp180", "label": "Weather", "params": {}}],
        extra_connections=[
            {"component_id": "weather", "pin_role": "VCC", "target": {"kind": "rail", "rail": "3V3"}},
            {"component_id": "weather", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "weather", "pin_role": "SDA", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "weather", "pin_role": "SCL", "target": {"kind": "bus", "bus_id": "i2c0"}},
        ],
    )
    parsed = yaml.unsafe_load(render_yaml(Design.model_validate(design_dict), library))
    bmp = next(s for s in parsed["sensor"] if s.get("platform") == "bmp085")
    assert bmp["i2c_id"] == "i2c0"
    assert bmp["temperature"]["name"] == "Weather Temperature"
    assert bmp["pressure"]["name"] == "Weather Pressure"


def test_htu21d_renders_temperature_and_humidity(library):
    design_dict = _esp32_with_i2c(
        components=[{"id": "th1", "library_id": "htu21d", "label": "Indoor", "params": {}}],
        extra_connections=[
            {"component_id": "th1", "pin_role": "VCC", "target": {"kind": "rail", "rail": "3V3"}},
            {"component_id": "th1", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "th1", "pin_role": "SDA", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "th1", "pin_role": "SCL", "target": {"kind": "bus", "bus_id": "i2c0"}},
        ],
    )
    parsed = yaml.unsafe_load(render_yaml(Design.model_validate(design_dict), library))
    htu = next(s for s in parsed["sensor"] if s.get("platform") == "htu21d")
    assert htu["temperature"]["name"] == "Indoor Temperature"
    assert htu["humidity"]["name"] == "Indoor Humidity"


def test_max31855_renders_with_spi_bus_and_cs(library):
    design_dict = _esp32_with_spi(
        components=[{"id": "tc1", "library_id": "max31855", "label": "Smoker probe",
                     "params": {"reference_temperature": True}}],
        extra_connections=[
            {"component_id": "tc1", "pin_role": "VCC",  "target": {"kind": "rail", "rail": "3V3"}},
            {"component_id": "tc1", "pin_role": "GND",  "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "tc1", "pin_role": "CLK",  "target": {"kind": "bus",  "bus_id": "spi0"}},
            {"component_id": "tc1", "pin_role": "MISO", "target": {"kind": "bus",  "bus_id": "spi0"}},
            {"component_id": "tc1", "pin_role": "CS",   "target": {"kind": "gpio", "pin": "GPIO5"}},
        ],
    )
    parsed = yaml.unsafe_load(render_yaml(Design.model_validate(design_dict), library))
    tc = next(s for s in parsed["sensor"] if s.get("platform") == "max31855")
    assert tc["spi_id"] == "spi0"
    assert tc["cs_pin"] == "GPIO5"
    assert tc["name"] == "Smoker probe Thermocouple"
    assert tc["reference_temperature"]["name"] == "Smoker probe Cold Junction"


def test_hx711_renders_with_dout_and_clk_pins(library):
    design_dict = _esp32_with_i2c(
        components=[{"id": "scale", "library_id": "hx711", "label": "Coffee scale",
                     "params": {"gain": 64}}],
        extra_connections=[
            {"component_id": "scale", "pin_role": "VCC",  "target": {"kind": "rail", "rail": "3V3"}},
            {"component_id": "scale", "pin_role": "GND",  "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "scale", "pin_role": "DOUT", "target": {"kind": "gpio", "pin": "GPIO16"}},
            {"component_id": "scale", "pin_role": "SCK",  "target": {"kind": "gpio", "pin": "GPIO17"}},
        ],
    )
    parsed = yaml.unsafe_load(render_yaml(Design.model_validate(design_dict), library))
    hx = next(s for s in parsed["sensor"] if s.get("platform") == "hx711")
    assert hx["dout_pin"] == "GPIO16"
    assert hx["clk_pin"] == "GPIO17"
    assert hx["gain"] == 64
    assert hx["name"] == "Coffee scale"


def test_tsl2561_renders_with_address_override(library):
    design_dict = _esp32_with_i2c(
        components=[{"id": "lux1", "library_id": "tsl2561", "label": "Window",
                     "params": {"address": "0x49", "gain": "16x", "integration_time": "402ms"}}],
        extra_connections=[
            {"component_id": "lux1", "pin_role": "VCC", "target": {"kind": "rail", "rail": "3V3"}},
            {"component_id": "lux1", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "lux1", "pin_role": "SDA", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "lux1", "pin_role": "SCL", "target": {"kind": "bus", "bus_id": "i2c0"}},
        ],
    )
    parsed = yaml.unsafe_load(render_yaml(Design.model_validate(design_dict), library))
    tsl = next(s for s in parsed["sensor"] if s.get("platform") == "tsl2561")
    assert tsl["address"] == "0x49"
    assert tsl["gain"] == "16x"
    assert tsl["integration_time"] == "402ms"
    assert tsl["name"] == "Window Illuminance"
