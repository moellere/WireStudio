from __future__ import annotations

from wirestudio.library import default_library
from wirestudio.model import Design
from wirestudio.targets.lorawan import codec


def _design(board_id: str, **lorawan) -> Design:
    return Design(
        schema_version="0.1",
        id="d",
        name="D",
        target="lorawan",
        lorawan=lorawan,
        board={"library_id": board_id, "mcu": "esp32"},
        power={"supply": "usb", "rail_voltage_v": 3.3},
    )


def test_builtin_only_layout():
    fields = codec.fields_for()  # no design -> built-in telemetry only
    assert [f["name"] for f in fields] == ["uptime_s", "boot_count"]
    assert codec.payload_size(fields) == 6


def test_tbeam_adds_onboard_gps_and_battery():
    lib = default_library()
    fields = codec.fields_for(_design("ttgo-t-beam"), lib)
    assert [f["name"] for f in fields] == [
        "uptime_s", "boot_count", "gps_lat", "gps_lon", "gps_alt_m", "gps_sats", "axp192_batt_mv",
    ]
    assert codec.payload_size(fields) == 19


def test_radio_only_board_is_builtin_only():
    lib = default_library()
    assert [f["name"] for f in codec.fields_for(_design("ttgo-lora32-v1"), lib)] == [
        "uptime_s", "boot_count",
    ]


def test_dht22_adds_temp_and_humidity():
    lib = default_library()
    design = _design("ttgo-t-beam", dht22={"pin": "GPIO13"})
    names = [f["name"] for f in codec.fields_for(design, lib)]
    assert "dht1_temp_c" in names and "dht1_humidity" in names
    # profile name reflects the sensor set (board GPS+battery + DHT)
    assert codec.profile_name(design, lib) == "wirestudio-ttgo-t-beam-us915-sub2-uart_gps-axp192-dht"


def test_oled_is_display_only_no_payload_field():
    lib = default_library()
    # An OLED adds no payload field (it's a display), so fields are unchanged.
    base = [f["name"] for f in codec.fields_for(_design("ttgo-t-beam"), lib)]
    witholed = [f["name"] for f in codec.fields_for(_design("ttgo-t-beam", oled={}), lib)]
    assert base == witholed


def test_external_gps_adds_gps_fields_without_battery():
    # Heltec has no onboard GPS/AXP; an external GPS config still adds GPS fields.
    lib = default_library()
    design = _design("heltec-wifi-lora32-v3", gps={"rx_pin": "GPIO3", "tx_pin": "GPIO1"})
    names = [f["name"] for f in codec.fields_for(design, lib)]
    assert "gps_lat" in names and "gps_sats" in names
    assert "batt_mv" not in names  # no AXP192 on the Heltec


def test_decode_js_offsets_and_scaling():
    js = codec.decode_js(codec.fields_for(_design("ttgo-t-beam"), default_library()))
    assert "function decodeUplink(input)" in js
    assert "data.gps_lat = ((b[6] << 24)" in js  # lat begins after the 6-byte built-in block
    assert "/ 10000000" in js
    assert "data.gps_alt_m = ((((b[14] << 8) | b[15]) << 16) >> 16)" in js  # signed 16-bit
    assert "data.axp192_batt_mv = (((b[17] << 8) | b[18]) >>> 0)" in js


def test_pack_cpp_matches_size_and_reads_sensors():
    fields = codec.fields_for(_design("ttgo-t-beam"), default_library())
    cpp = codec.pack_cpp(fields)
    assert f"payload[{codec.payload_size(fields) - 1}]" in cpp
    assert "gps.location.lat()" in cpp
    assert "batteryMv" in cpp


def test_generate_codec_includes_decode_and_ha_device_info():
    js = codec.generate_codec(_design("ttgo-t-beam"), default_library())
    assert "function decodeUplink(input)" in js
    assert "function getHaDeviceInfo()" in js


def test_ha_device_info_entities_and_units():
    lib = default_library()
    js = codec.generate_codec(_design("ttgo-t-beam", dht22={"pin": "GPIO13"}), lib)
    # payload fields become entities with proper templates/units
    assert 'value_template: "{{ value_json.object.temp_c | float }}"' in js
    assert 'device_class: "temperature"' in js
    # battery is converted mV -> V in the HA template
    assert "(value_json.object.batt_mv | float) / 1000" in js
    assert 'device_class: "voltage"' in js
    # link quality from rxInfo (not payload)
    assert "value_json.rxInfo[-1].rssi | int" in js


def test_ha_device_info_gps_emits_device_tracker():
    lib = default_library()
    gps_js = codec.generate_codec(_design("ttgo-t-beam"), lib)  # onboard GPS
    assert 'integration: "device_tracker"' in gps_js
    assert "'latitude': value_json.object.lat" in gps_js
    assert 'json_attributes_topic: "{status_topic}"' in gps_js
    # a non-GPS board gets no device_tracker
    plain_js = codec.generate_codec(_design("ttgo-lora32-v1"), lib)
    assert "device_tracker" not in plain_js
