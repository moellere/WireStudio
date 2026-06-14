"""Uplink payload layout + matching ChirpStack codec, from one source of truth.

The firmware's byte packing and ChirpStack's ``decodeUplink`` JS are both
generated from the same field list, so they can't drift -- the lockstep the
plan (§9) calls for. Fields are packed big-endian.

``fields_for(board)`` assembles the payload: always-on built-in telemetry, plus
fields contributed by the board's onboard sensors (GPS, battery) when present.
``pack_cpp`` emits the C++ that fills the payload buffer (referencing the globals
the firmware template declares: ``gps``, ``batteryMv``, ``bootCount``);
``decode_js`` emits the ChirpStack codec that reads it back into named fields.
"""
from __future__ import annotations

from typing import Optional, TypedDict


class Field(TypedDict, total=False):
    name: str
    bytes: int
    cpp_type: str
    cpp_expr: str  # C++ expression yielding the value (assigned to a temp, then packed)
    signed: bool   # default False; affects codec sign-extension
    scale: float   # default 1; codec divides the decoded int by this (e.g. 1e7 for degrees)
    # Home Assistant entity hints, consumed by `getHaDeviceInfo` (the chirp2mqtt
    # integration reads them to publish MQTT-discovery entities). All optional.
    ha_device_class: str   # HA device_class (e.g. "temperature", "voltage")
    ha_unit: str           # unit_of_measurement
    ha_state_class: str    # e.g. "measurement"
    ha_diagnostic: bool    # entity_category=diagnostic
    ha_icon: str           # mdi icon
    ha_divide: float       # divide the (already decoded) value in the HA template


# Always present on every LoRaWAN build. Big-endian.
BUILTIN_FIELDS: list[Field] = [
    {"name": "uptime_s", "bytes": 4, "cpp_type": "uint32_t", "cpp_expr": "(uint32_t)(millis() / 1000UL)",
     "ha_device_class": "duration", "ha_unit": "s", "ha_diagnostic": True},
    {"name": "boot_count", "bytes": 2, "cpp_type": "uint16_t", "cpp_expr": "bootCount",
     "ha_state_class": "measurement", "ha_diagnostic": True, "ha_icon": "mdi:restart"},
]

# Added when the board carries a `gps_neo6m` onboard peripheral. lat/lon are
# scaled by 1e7 into signed int32 (standard LoRaWAN GPS encoding). With no fix,
# TinyGPSPlus returns 0 -> sats=0 is the "no fix yet" indicator.
GPS_FIELDS: list[Field] = [
    {"name": "lat", "bytes": 4, "cpp_type": "int32_t",
     "cpp_expr": "(int32_t)(gps.location.lat() * 10000000.0)", "signed": True, "scale": 1e7,
     "ha_unit": "°", "ha_diagnostic": True, "ha_icon": "mdi:latitude"},
    {"name": "lon", "bytes": 4, "cpp_type": "int32_t",
     "cpp_expr": "(int32_t)(gps.location.lng() * 10000000.0)", "signed": True, "scale": 1e7,
     "ha_unit": "°", "ha_diagnostic": True, "ha_icon": "mdi:longitude"},
    {"name": "alt_m", "bytes": 2, "cpp_type": "int16_t",
     "cpp_expr": "(int16_t)gps.altitude.meters()", "signed": True,
     "ha_device_class": "distance", "ha_unit": "m", "ha_state_class": "measurement", "ha_diagnostic": True},
    {"name": "sats", "bytes": 1, "cpp_type": "uint8_t",
     "cpp_expr": "(uint8_t)gps.satellites.value()",
     "ha_state_class": "measurement", "ha_diagnostic": True, "ha_icon": "mdi:satellite-variant"},
]

# Added when the board carries an `axp192` PMIC. batteryMv is read in the loop.
BATTERY_FIELDS: list[Field] = [
    {"name": "batt_mv", "bytes": 2, "cpp_type": "uint16_t", "cpp_expr": "batteryMv",
     "ha_device_class": "voltage", "ha_unit": "V", "ha_state_class": "measurement",
     "ha_diagnostic": True, "ha_divide": 1000},
]

# Added when the design declares a `dht22`. Temperature signed int16 x100 (degC);
# humidity uint8 (%). dhtTempC / dhtHumidity are read into globals in the loop.
DHT_FIELDS: list[Field] = [
    {"name": "temp_c", "bytes": 2, "cpp_type": "int16_t",
     "cpp_expr": "(int16_t)(dhtTempC * 100.0)", "signed": True, "scale": 100,
     "ha_device_class": "temperature", "ha_unit": "°C", "ha_state_class": "measurement"},
    {"name": "humidity", "bytes": 1, "cpp_type": "uint8_t", "cpp_expr": "(uint8_t)dhtHumidity",
     "ha_device_class": "humidity", "ha_unit": "%", "ha_state_class": "measurement"},
]


def fields_for(design=None, library=None) -> list[Field]:
    """Payload fields: built-in telemetry + fields contributed by components."""
    fields = list(BUILTIN_FIELDS)
    if design is None or library is None:
        return fields

    components = list(design.components)
    board = library.board(design.board.library_id)
    onboard = board.onboard_peripherals or {}
    lw = getattr(design, "lorawan", None)

    has_gps = any(c.library_id == "uart_gps" for c in components)
    has_dht = any(c.library_id == "dht" for c in components)
    has_axp = any(c.library_id == "axp192" for c in components)
    has_oled = any(c.library_id == "ssd1306" for c in components)

    if "gps_neo6m" in onboard or getattr(lw, "gps", None) is not None:
        if not has_gps:
            from wirestudio.model import Component
            components.append(Component(id="gps", library_id="uart_gps", label="GPS"))

    if "axp192" in onboard and not has_axp:
        from wirestudio.model import Component
        components.append(Component(id="axp192", library_id="axp192", label="PMIC"))

    if getattr(lw, "dht22", None) is not None and not has_dht:
        from wirestudio.model import Component
        components.append(Component(id="dht1", library_id="dht", label="DHT"))

    if "oled_ssd1306" in onboard or getattr(lw, "oled", None) is not None:
        if not has_oled:
            from wirestudio.model import Component
            components.append(Component(id="oled", library_id="ssd1306", label="OLED"))

    for comp_inst in components:
        try:
            lib_comp = library.component(comp_inst.library_id)
            if lib_comp.lorawan and lib_comp.lorawan.fields:
                for fld in lib_comp.lorawan.fields:
                    fields.append({
                        "name": f"{comp_inst.id}_{fld.name}",
                        "bytes": fld.bytes,
                        "cpp_type": fld.cpp_type,
                        "cpp_expr": fld.cpp_expr.replace("{{ id }}", comp_inst.id),
                        "signed": fld.signed,
                        "scale": fld.scale
                    })
        except Exception:
            pass

    return fields

def payload_size(fields: list[Field]) -> int:
    return sum(f["bytes"] for f in fields)


def pack_cpp(fields: list[Field], *, indent: str = "  ") -> str:
    """C++ that fills `uint8_t payload[N]` big-endian from the field expressions."""
    lines: list[str] = []
    offset = 0
    for fld in fields:
        var = f"_v_{fld['name']}"
        lines.append(f"{indent}{fld['cpp_type']} {var} = {fld['cpp_expr']};")
        for i in range(fld["bytes"]):
            shift = 8 * (fld["bytes"] - 1 - i)
            expr = f"{var} >> {shift}" if shift else var
            lines.append(f"{indent}payload[{offset}] = (uint8_t)({expr});")
            offset += 1
    return "\n".join(lines)


def decode_js(fields: list[Field]) -> str:
    """ChirpStack `decodeUplink` reading the same big-endian layout, honoring
    each field's signedness and scale."""
    lines = ["function decodeUplink(input) {", "  var b = input.bytes;", "  var data = {};"]
    offset = 0
    for fld in fields:
        nbits = fld["bytes"] * 8
        parts = []
        for i in range(fld["bytes"]):
            shift = 8 * (fld["bytes"] - 1 - i)
            parts.append(f"(b[{offset}] << {shift})" if shift else f"b[{offset}]")
            offset += 1
        raw = " | ".join(parts)
        if fld.get("signed"):
            # JS bitops are signed 32-bit: a 32-bit field is already signed;
            # narrower fields need sign extension.
            value = f"({raw})" if nbits == 32 else f"((({raw}) << {32 - nbits}) >> {32 - nbits})"
        else:
            value = f"(({raw}) >>> 0)"  # coerce to unsigned 32-bit
        scale = fld.get("scale", 1)
        if scale and scale != 1:
            value = f"{value} / {scale:.0f}"
        lines.append(f"  data.{fld['name']} = {value};")
    lines += ["  return { data: data, warnings: [], errors: [] };", "}", ""]
    return "\n".join(lines)


# Link-quality entities every device exposes, read from ChirpStack's rxInfo
# (not the payload). Appended to every getHaDeviceInfo.
_RX_ENTITIES: list[tuple[str, str, dict]] = [
    ("rssi", "value_json.rxInfo[-1].rssi | int",
     {"ha_device_class": "signal_strength", "ha_unit": "dBm", "ha_diagnostic": True}),
    ("snr", "value_json.rxInfo[-1].snr | float",
     {"ha_unit": "dB", "ha_diagnostic": True, "ha_icon": "mdi:wave"}),
]


def _ha_entity_conf(value_template: str, hints: dict) -> str:
    """Render one chirp2mqtt `entity_conf` block from HA hints."""
    lines = [f'        value_template: "{{{{ {value_template} }}}}"']
    if hints.get("ha_diagnostic"):
        lines.append('        entity_category: "diagnostic"')
    if hints.get("ha_state_class"):
        lines.append(f'        state_class: "{hints["ha_state_class"]}"')
    if hints.get("ha_device_class"):
        lines.append(f'        device_class: "{hints["ha_device_class"]}"')
    if hints.get("ha_unit"):
        lines.append(f'        unit_of_measurement: "{hints["ha_unit"]}"')
    if hints.get("ha_icon"):
        lines.append(f'        icon: "{hints["ha_icon"]}"')
    return "{\n" + ",\n".join(lines) + "\n      }"


def ha_device_info_js(fields: list[Field], *, model: str) -> str:
    """ChirpStack-codec `getHaDeviceInfo` for the chirp2mqtt HA integration.

    chirp2mqtt reads this function (not just `decodeUplink`) to publish HA
    MQTT-discovery entities. Each payload field with HA hints becomes a sensor;
    rssi/snr come from rxInfo; a GPS payload (lat+lon) also yields a
    `device_tracker` whose latitude/longitude attributes drive the HA map.
    """
    blocks: list[str] = []
    for fld in fields:
        if not any(k.startswith("ha_") for k in fld):
            continue
        expr = f"value_json.object.{fld['name']} | {'float' if fld['cpp_type'].startswith(('int', 'float')) or fld.get('scale') else 'int'}"
        if fld.get("ha_divide"):
            expr = f"(value_json.object.{fld['name']} | float) / {fld['ha_divide']:.0f}"
        blocks.append(f"    {fld['name']}: {{\n      entity_conf: {_ha_entity_conf(expr, fld)}\n    }}")
    for name, expr, hints in _RX_ENTITIES:
        blocks.append(f"    {name}: {{\n      entity_conf: {_ha_entity_conf(expr, hints)}\n    }}")
    names = {f["name"] for f in fields}
    if {"lat", "lon"} <= names:
        blocks.append(
            '    location: {\n'
            '      integration: "device_tracker",\n'
            '      entity_conf: {\n'
            '        source_type: "gps",\n'
            "        value_template: \"{{ 'home' if (value_json.object.sats | int) > 0 else 'not_home' }}\",\n"
            '        json_attributes_topic: "{status_topic}",\n'
            "        json_attributes_template: \"{{ {'latitude': value_json.object.lat, 'longitude': value_json.object.lon, 'gps_accuracy': 10} | tojson }}\"\n"
            '      }\n'
            '    }'
        )
    return (
        "\nfunction getHaDeviceInfo() {\n  return {\n"
        f'    device: {{ manufacturer: "wirestudio", model: "{model}" }},\n'
        "    entities: {\n" + ",\n".join(blocks) + "\n    }\n  };\n}\n"
    )


def generate_codec(design=None, library=None) -> str:
    """The ChirpStack codec for a design's payload: `decodeUplink` plus the
    `getHaDeviceInfo` block the chirp2mqtt HA integration reads to publish
    MQTT-discovery entities."""
    fields = fields_for(design, library)
    return decode_js(fields) + ha_device_info_js(fields, model=profile_name(design, library))



def profile_name(design=None, library=None) -> str:
    """ChirpStack device-profile name for a design's payload shape."""
    board_id = getattr(getattr(design, "board", None), "library_id", "generic")
    suffix = ""
    if design and library:
        components = list(design.components)
        board = library.board(design.board.library_id)
        onboard = board.onboard_peripherals or {}
        lw = getattr(design, "lorawan", None)

        has_gps = any(c.library_id == "uart_gps" for c in components)
        has_dht = any(c.library_id == "dht" for c in components)
        has_axp = any(c.library_id == "axp192" for c in components)
        has_oled = any(c.library_id == "ssd1306" for c in components)

        if "gps_neo6m" in onboard or getattr(lw, "gps", None) is not None:
            if not has_gps:
                from wirestudio.model import Component
                components.append(Component(id="gps", library_id="uart_gps", label="GPS"))

        if "axp192" in onboard and not has_axp:
            from wirestudio.model import Component
            components.append(Component(id="axp192", library_id="axp192", label="PMIC"))

        if getattr(lw, "dht22", None) is not None and not has_dht:
            from wirestudio.model import Component
            components.append(Component(id="dht1", library_id="dht", label="DHT"))

        if "oled_ssd1306" in onboard or getattr(lw, "oled", None) is not None:
            if not has_oled:
                from wirestudio.model import Component
                components.append(Component(id="oled", library_id="ssd1306", label="OLED"))

        for comp_inst in components:
            suffix += f"-{comp_inst.library_id}"

    if len(suffix) > 30:
        import hashlib
        suffix = "-" + hashlib.md5(suffix.encode()).hexdigest()[:8]

    return f"wirestudio-{board_id}-us915-sub2{suffix}"

def builtin_codec() -> Optional[str]:
    return decode_js(BUILTIN_FIELDS)
