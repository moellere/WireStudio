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


def generate_codec(design=None, library=None) -> str:
    """The ChirpStack codec for a design's payload."""
    return decode_js(fields_for(design, library))



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
