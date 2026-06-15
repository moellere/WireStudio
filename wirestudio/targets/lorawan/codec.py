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

def _pin(value) -> Optional[int]:
    """Board pins are 'GPIO18'; Arduino wants the bare number 18. Idempotent on
    ints and tolerant of None."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return int(str(value).removeprefix("GPIO"))


# Onboard peripherals the LoRaWAN firmware materializes implicitly when the
# board declares them (or the design's `lorawan.*` config asks for them) and
# the user hasn't already added the matching component. Order here is the
# *payload* field order, fixed to keep the uplink byte layout (and ChirpStack
# decode) stable: GPS, battery, DHT. (Firmware setup() reorders to a hardware
# init order -- PMIC first -- see firmware_gen._SETUP_PRIORITY.) `tag` is the
# device-profile suffix the field set historically carried, so provisioned
# devices keep their profile names.
_ONBOARD = [
    ("uart_gps", "gps_neo6m", "gps", "GPS", "gps"),
    ("axp192", "axp192", "axp192", "PMIC", "batt"),
    ("dht", None, "dht1", "DHT", "dht"),
    ("ssd1306", "oled_ssd1306", "oled", "OLED", None),
]
_PROFILE_ORDER = ["gps", "batt", "dht"]


def resolve_components(design, library) -> list:
    """The full LoRaWAN component set: the design's own components plus the
    board's onboard peripherals (and `lorawan.*`-requested sensors) synthesized
    as components, so firmware_gen and the codec assemble from one inventory and
    can't drift. Synthesized peripherals carry pin/config params (pins
    normalized to bare ints) and a stable id; an onboard peripheral whose
    library component the user already added is not duplicated."""
    from wirestudio.model import Component

    components = list(design.components)
    present = {c.library_id for c in components}
    used_ids = {c.id for c in components}
    board = library.board(design.board.library_id)
    onboard = board.onboard_peripherals or {}
    lw = getattr(design, "lorawan", None)

    synth: list = []
    for lib_id, onboard_key, inst_id, label, _tag in _ONBOARD:
        # Don't duplicate a peripheral the user already placed, and don't let a
        # synthesized id collide with an existing component's id.
        if lib_id in present or inst_id in used_ids:
            continue
        params = _synth_params(lib_id, onboard_key, onboard, lw)
        if params is None:
            continue
        synth.append(Component(id=inst_id, library_id=lib_id, label=label, params=params))
        used_ids.add(inst_id)
    return components + synth


def _synth_params(lib_id, onboard_key, onboard, lw):
    """Params for a synthesized onboard peripheral, or None when the board /
    design doesn't call for it. Pin params are normalized to bare ints."""
    on = onboard_key in onboard if onboard_key else False
    if lib_id == "axp192":
        return {} if on else None
    if lib_id == "uart_gps":
        gps = getattr(lw, "gps", None)
        if gps is not None:
            return {"rx_pin": _pin(gps.rx_pin), "tx_pin": _pin(gps.tx_pin), "baud": gps.baud}
        if on:
            ob = onboard[onboard_key]
            # The peripheral's TX is the MCU's RX (and vice-versa).
            return {"rx_pin": _pin(ob.get("tx")), "tx_pin": _pin(ob.get("rx")),
                    "baud": ob.get("baud", 9600)}
        return None
    if lib_id == "dht":
        dht = getattr(lw, "dht22", None)
        return {"pin": _pin(dht.pin), "model": "DHT22"} if dht is not None else None
    if lib_id == "ssd1306":
        oled = getattr(lw, "oled", None)
        if not on and oled is None:
            return None
        params: dict = {}
        ob = onboard.get(onboard_key) or {}
        if ob:
            params["address"] = ob.get("address", "0x3C")
            if ob.get("reset"):
                params["reset_pin"] = _pin(ob["reset"])
            if ob.get("vext"):
                params["vext_pin"] = _pin(ob["vext"])
        return params
    return None


def _field_dict(fld) -> Field:
    """Convert a library `LorawanField` to a codec `Field`, emitting only the
    keys that affect output -- so a migrated field reproduces its old dict (and
    thus byte-identical codec) exactly. `scale`/`signed` are omitted at their
    defaults; HA hints only when set."""
    d: Field = {"name": fld.name, "bytes": fld.bytes,
                "cpp_type": fld.cpp_type, "cpp_expr": fld.cpp_expr}
    if fld.signed:
        d["signed"] = True
    if fld.scale and fld.scale != 1.0:
        d["scale"] = fld.scale
    for attr in ("ha_device_class", "ha_unit", "ha_state_class",
                 "ha_diagnostic", "ha_icon", "ha_divide"):
        v = getattr(fld, attr)
        if v is not None and v is not False:
            d[attr] = v
    return d


def fields_for(design=None, library=None) -> list[Field]:
    """Payload fields: built-in telemetry + fields contributed by every
    resolved component's `lorawan.fields`. Raises on a duplicate field name so
    a collision is a loud error, not a silent pack/decode mismatch."""
    fields = list(BUILTIN_FIELDS)
    if design is None or library is None:
        return fields
    seen = {f["name"] for f in fields}
    for comp in resolve_components(design, library):
        lib_comp = library.component(comp.library_id)
        if not (lib_comp.lorawan and lib_comp.lorawan.fields):
            continue
        for fld in lib_comp.lorawan.fields:
            if fld.name in seen:
                raise ValueError(
                    f"duplicate lorawan payload field {fld.name!r} "
                    f"(component {comp.id!r}); field names must be unique"
                )
            seen.add(fld.name)
            fields.append(_field_dict(fld))
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
    """ChirpStack device-profile name for a design's payload shape. Distinct
    payloads (board + attached sensors) get distinct profiles, so each carries
    its own decodeUplink codec without clobbering another device type's. The
    suffix is the stable set of payload-bearing sensor tags (`-gps`/`-batt`/
    `-dht`) in a fixed order, so provisioned devices keep their profile name."""
    board_id = getattr(getattr(design, "board", None), "library_id", "generic")
    tags: set[str] = set()
    if design and library:
        tag_for = {lib_id: tag for lib_id, _k, _i, _l, tag in _ONBOARD if tag}
        for comp in resolve_components(design, library):
            tag = tag_for.get(comp.library_id)
            if tag:
                tags.add(tag)
    suffix = "".join(f"-{t}" for t in _PROFILE_ORDER if t in tags)
    return f"wirestudio-{board_id}-us915-sub2{suffix}"


def builtin_codec() -> Optional[str]:
    return decode_js(BUILTIN_FIELDS)
