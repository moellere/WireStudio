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


# Always present on every LoRaWAN build. Big-endian.
BUILTIN_FIELDS: list[Field] = [
    {"name": "uptime_s", "bytes": 4, "cpp_type": "uint32_t", "cpp_expr": "(uint32_t)(millis() / 1000UL)"},
    {"name": "boot_count", "bytes": 2, "cpp_type": "uint16_t", "cpp_expr": "bootCount"},
]

# Added when the board carries a `gps_neo6m` onboard peripheral. lat/lon are
# scaled by 1e7 into signed int32 (standard LoRaWAN GPS encoding). With no fix,
# TinyGPSPlus returns 0 -> sats=0 is the "no fix yet" indicator.
GPS_FIELDS: list[Field] = [
    {"name": "lat", "bytes": 4, "cpp_type": "int32_t",
     "cpp_expr": "(int32_t)(gps.location.lat() * 10000000.0)", "signed": True, "scale": 1e7},
    {"name": "lon", "bytes": 4, "cpp_type": "int32_t",
     "cpp_expr": "(int32_t)(gps.location.lng() * 10000000.0)", "signed": True, "scale": 1e7},
    {"name": "alt_m", "bytes": 2, "cpp_type": "int16_t",
     "cpp_expr": "(int16_t)gps.altitude.meters()", "signed": True},
    {"name": "sats", "bytes": 1, "cpp_type": "uint8_t",
     "cpp_expr": "(uint8_t)gps.satellites.value()"},
]

# Added when the board carries an `axp192` PMIC. batteryMv is read in the loop.
BATTERY_FIELDS: list[Field] = [
    {"name": "batt_mv", "bytes": 2, "cpp_type": "uint16_t", "cpp_expr": "batteryMv"},
]

# Added when the design declares a `dht22`. Temperature signed int16 x100 (degC);
# humidity uint8 (%). dhtTempC / dhtHumidity are read into globals in the loop.
DHT_FIELDS: list[Field] = [
    {"name": "temp_c", "bytes": 2, "cpp_type": "int16_t",
     "cpp_expr": "(int16_t)(dhtTempC * 100.0)", "signed": True, "scale": 100},
    {"name": "humidity", "bytes": 1, "cpp_type": "uint8_t", "cpp_expr": "(uint8_t)dhtHumidity"},
]


def sensors(design=None, library=None) -> dict:
    """Which sensors a design has, from onboard peripherals + lorawan.* configs.
    firmware_gen and the codec both use this, so they stay in lockstep.
    Keys: gps, battery, dht, oled (oled is display-only, no payload field)."""
    onboard: dict = {}
    if design is not None and library is not None:
        try:
            onboard = library.board(design.board.library_id).onboard_peripherals or {}
        except (FileNotFoundError, AttributeError):
            onboard = {}
    lw = getattr(design, "lorawan", None)
    return {
        "gps": ("gps_neo6m" in onboard) or (getattr(lw, "gps", None) is not None),
        "battery": "axp192" in onboard,
        "dht": getattr(lw, "dht22", None) is not None,
        "oled": ("oled_ssd1306" in onboard) or (getattr(lw, "oled", None) is not None),
    }


def fields_for(design=None, library=None) -> list[Field]:
    """Payload fields: built-in telemetry + GPS / battery / DHT when present."""
    s = sensors(design, library)
    fields = list(BUILTIN_FIELDS)
    if s["gps"]:
        fields += GPS_FIELDS
    if s["battery"]:
        fields += BATTERY_FIELDS
    if s["dht"]:
        fields += DHT_FIELDS
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


def generate_codec(design=None, library=None) -> str:
    """The ChirpStack codec for a design's payload."""
    return decode_js(fields_for(design, library))


def profile_name(design=None, library=None) -> str:
    """ChirpStack device-profile name for a design's payload shape. Distinct
    payloads (board + attached sensors) get distinct profiles, so each carries
    its own decodeUplink codec without clobbering another device type's."""
    s = sensors(design, library)
    board_id = getattr(getattr(design, "board", None), "library_id", "generic")
    suffix = "".join(
        tag for tag, on in (("-gps", s["gps"]), ("-batt", s["battery"]), ("-dht", s["dht"])) if on
    )
    return f"wirestudio-{board_id}-us915-sub2{suffix}"


def builtin_codec() -> Optional[str]:
    return decode_js(BUILTIN_FIELDS)
