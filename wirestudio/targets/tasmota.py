"""Tasmota target: emit a device template from a solved design.

A Tasmota template is a JSON mapping of the chip's user GPIOs to
function ids -- exactly what the pin solver produces. Generation is a
pure function of the design; no toolchain, no compile. Paste the
template into the Tasmota web UI (Configuration -> Other) or apply it
with the `Template` console command, then `Module 0` to activate.

Function values come from tasmota_template.h's UserSelectablePins enum:
JSON value = enum_index << 5, plus the 0-based unit for numbered
families (Relay2 = 224 + 1). Verified against arendst/Tasmota master
and the blakadder template database (Relay1=224, Button1=32,
Switch1=160, I2C SDA=640/SCL=608).

I2C sensors need no per-component mapping -- Tasmota autodetects them
once the bus pins carry I2C_SDA/I2C_SCL, so only the bus contributes.

CLI: `python -m wirestudio.targets.tasmota <design.json>`.
"""
from __future__ import annotations

import json
from typing import Optional

from wirestudio.library import Library
from wirestudio.model import Design, DesignWarning
from wirestudio.targets.base import TargetPlugin, register

FUNC = {
    "None": 0,
    "Button": 32,
    "Switch": 160,
    "Relay": 224,
    "Led": 288,
    "Counter": 352,
    "PWM": 416,
    "Buzzer": 480,
    "LedLink": 544,
    "I2C_SCL": 608,
    "I2C_SDA": 640,
    "IRsend": 1056,
    "IRrecv": 1088,
    "DHT11": 1184,
    "DHT22": 1216,
    "SI7021": 1248,
    "DS18x20": 1312,
    "WS2812": 1376,
    "SR04_Trig": 1856,
    "SR04_Echo": 1888,
    "TM1638_CLK": 2048,
    "TM1638_DIO": 2080,
    "TM1638_STB": 2112,
    "HX711_SCK": 2176,
    "HX711_DAT": 2208,
    "NRG_SEL": 2592,
    "NRG_CF1": 2656,
    "HLW_CF": 2688,
    "CSE7766_TX": 3072,
    "CSE7766_RX": 3104,
    "Rotary_A": 3264,
    "Rotary_B": 3296,
    "ADC_Input": 4704,
    "MAX7219_CLK": 7392,
    "MAX7219_DIN": 7424,
    "MAX7219_CS": 7456,
}

# Families where repeated use numbers the unit (Relay1, Relay2, ...).
_UNIT_MAX = {"Button": 4, "Switch": 8, "Relay": 8, "Led": 4, "Counter": 4, "PWM": 5}

# Template slot order per chip: the physical GPIO each array position
# addresses, from tasmota_template.h. ESP8266 slot 13 is ADC0 (GPIO17);
# classic ESP32 interleaves flash pins 6/7/8/11 at slots 24-27 for
# backward compatibility (ESP32_TEMPLATE_TO_PHY).
_CHIP_SLOTS: dict[str, list[int]] = {
    "esp8266": [0, 1, 2, 3, 4, 5, 9, 10, 12, 13, 14, 15, 16, 17],
    "esp8285": [0, 1, 2, 3, 4, 5, 9, 10, 12, 13, 14, 15, 16, 17],
    "esp32": [0, 1, 2, 3, 4, 5, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19,
              20, 21, 22, 23, 24, 25, 26, 27, 6, 7, 8, 11,
              32, 33, 34, 35, 36, 37, 38, 39],
    "esp32s2": list(range(0, 22)) + list(range(33, 47)),
    "esp32s3": list(range(0, 22)) + list(range(33, 49)),
    "esp32c3": list(range(0, 22)),
    "esp32c6": list(range(0, 31)),
}

_DHT_MODELS = {"DHT11": "DHT11", "SI7021": "SI7021"}

# Official release images from Tasmota's OTA server, flashed at 0x0.
# ESP8266 uses the plain app image (it includes the boot stub); ESP32
# variants need the .factory image (bootloader + partitions + app).
_OTA_BASE_8266 = "http://ota.tasmota.com/tasmota/release"
_OTA_BASE_32 = "http://ota.tasmota.com/tasmota32/release"
_FIRMWARE: dict[str, tuple[str, int]] = {
    "esp8266": (f"{_OTA_BASE_8266}/tasmota.bin", 0x0),
    "esp8285": (f"{_OTA_BASE_8266}/tasmota.bin", 0x0),
    "esp32": (f"{_OTA_BASE_32}/tasmota32.factory.bin", 0x0),
    "esp32s2": (f"{_OTA_BASE_32}/tasmota32s2.factory.bin", 0x0),
    "esp32s3": (f"{_OTA_BASE_32}/tasmota32s3.factory.bin", 0x0),
    "esp32c3": (f"{_OTA_BASE_32}/tasmota32c3.factory.bin", 0x0),
    "esp32c6": (f"{_OTA_BASE_32}/tasmota32c6.factory.bin", 0x0),
}

_FIRMWARE_TIMEOUT = 60  # seconds; release images are ~1-2 MB


def _fetch_firmware(url: str) -> bytes:
    import httpx

    resp = httpx.get(url, timeout=_FIRMWARE_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def firmware_status() -> dict:
    """Probe whether the server can reach Tasmota's OTA host. Mirrors the
    other feature-gate status endpoints; the web UI gates the Flash
    button on `available` and surfaces `reason`."""
    import httpx

    try:
        resp = httpx.head(
            f"{_OTA_BASE_8266}/tasmota.bin", timeout=10, follow_redirects=True
        )
        available = resp.status_code < 400
        reason = None if available else f"OTA server returned {resp.status_code}"
    except Exception as e:
        available, reason = False, f"OTA server unreachable: {e}"
    return {"available": available, "chips": sorted(_FIRMWARE), "reason": reason}


def _pin_number(pin: str) -> Optional[int]:
    digits = "".join(ch for ch in pin if ch.isdigit())
    return int(digits) if digits else None


def build_template(design: Design, library: Library) -> tuple[dict, list[str]]:
    """The template dict plus human-readable warnings for anything the
    design contains that Tasmota can't express."""
    board = library.board(design.board.library_id)
    slots = _CHIP_SLOTS.get(board.chip_variant)
    if slots is None:
        raise ValueError(
            f"Tasmota has no template layout for chip '{board.chip_variant}'"
        )

    assignments: dict[int, int] = {}
    warnings: list[str] = []
    unit_used: dict[str, int] = {}

    def assign(pin: str, func_name: str, owner: str) -> None:
        num = _pin_number(pin)
        if num is None or num not in slots:
            warnings.append(f"{owner}: pin {pin} is not templatable on {board.chip_variant}")
            return
        base = FUNC[func_name]
        cap = _UNIT_MAX.get(func_name)
        if cap is not None:
            unit = unit_used.get(func_name, 0)
            if unit >= cap:
                warnings.append(f"{owner}: more than {cap} {func_name} pins; skipped")
                return
            unit_used[func_name] = unit + 1
            base += unit
        if num in assignments:
            warnings.append(f"{owner}: pin {pin} already assigned; skipped")
            return
        assignments[num] = base

    buses = {b.id: b for b in design.buses}
    for bus in buses.values():
        if bus.type == "i2c":
            for role, func in (("sda", "I2C_SDA"), ("scl", "I2C_SCL")):
                pin = getattr(bus, role, None)
                if pin:
                    assign(pin, func, f"bus {bus.id}")

    for comp in design.components:
        lib_comp = library.component(comp.library_id)
        spec = lib_comp.tasmota
        conns = [c for c in design.connections if c.component_id == comp.id]
        i2c_only = "i2c" in lib_comp.esphome.required_components
        if spec is None:
            if not i2c_only:
                warnings.append(
                    f"{comp.id} ({comp.library_id}): no Tasmota mapping; not in template"
                )
            continue

        for conn in conns:
            func_name = spec.pins.get(conn.pin_role)
            t = conn.target
            if func_name is not None:
                if lib_comp.id == "dht":
                    model = str((comp.params or {}).get("model", "")).upper()
                    func_name = _DHT_MODELS.get(model, func_name)
                if t.kind == "gpio" and t.pin:
                    assign(t.pin, func_name, comp.id)
                else:
                    warnings.append(
                        f"{comp.id}.{conn.pin_role}: only direct GPIO wiring is "
                        f"templatable (target is {t.kind})"
                    )
            elif spec.bus and t.kind == "bus":
                bus = buses.get(t.bus_id or "")
                if bus is None:
                    continue
                for bus_role, bus_func in spec.bus.items():
                    pin = getattr(bus, bus_role, None)
                    if pin:
                        assign(pin, bus_func, comp.id)

    gpio = [assignments.get(phys, 0) for phys in slots]
    template = {
        "NAME": str(design.name or design.id)[:14],
        "GPIO": gpio,
        "FLAG": 0,
        "BASE": 18 if board.chip_variant.startswith("esp82") else 1,
    }
    return template, warnings


class TasmotaTarget(TargetPlugin):
    """Emit a Tasmota device template. Pure mapping; no build step."""

    id = "tasmota"

    def board_ids(self, library: Library) -> list[str]:
        return sorted(
            b.id for b in library.list_boards() if b.chip_variant in _CHIP_SLOTS
        )

    def component_ids(self, library: Library) -> list[str]:
        return sorted(
            c.id for c in library.list_components()
            if c.tasmota is not None or "i2c" in c.esphome.required_components
        )

    def generate(self, design: Design, library: Library) -> dict[str, str]:
        template, warnings = build_template(design, library)
        files = {"template.json": json.dumps(template) + "\n"}
        if warnings:
            files["template-warnings.txt"] = "\n".join(warnings) + "\n"
        return files

    def validate(self, design: Design, library: Library) -> list[DesignWarning]:
        try:
            _, warnings = build_template(design, library)
        except (ValueError, FileNotFoundError):
            return []
        return [
            DesignWarning(level="info", code="tasmota_untemplatable", text=w)
            for w in warnings
        ]

    def router(self, library: Library):
        from fastapi import APIRouter, HTTPException, Response

        router = APIRouter(tags=["tasmota"])

        @router.post("/template")
        def tasmota_template(design: dict) -> dict:
            d = Design.model_validate(design)
            try:
                template, warnings = build_template(d, library)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e)) from e
            except FileNotFoundError as e:
                raise HTTPException(status_code=404, detail=str(e)) from e
            return {"template": template, "warnings": warnings}

        @router.get("/firmware/status")
        def tasmota_firmware_status() -> dict:
            return firmware_status()

        # No return annotation: `from __future__ import annotations` turns it
        # into a string that OpenAPI generation can't resolve for the
        # locally-imported Response.
        @router.get("/firmware", response_class=Response)
        def tasmota_firmware(chip: str):
            source = _FIRMWARE.get(chip)
            if source is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"no Tasmota release image for chip '{chip}'",
                )
            url, offset = source
            try:
                data = _fetch_firmware(url)
            except Exception as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"could not fetch {url}: {e}",
                ) from e
            return Response(
                content=data,
                media_type="application/octet-stream",
                headers={
                    "X-Flash-Offset": str(offset),
                    "Content-Disposition": f'attachment; filename="{url.rsplit("/", 1)[-1]}"',
                },
            )

        return router


# Under `python -m wirestudio.targets.tasmota` runpy executes this module
# body a second time after the package import already registered it.
try:
    register(TasmotaTarget())
except ValueError:
    pass


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    from wirestudio.library import default_library

    parser = argparse.ArgumentParser(
        prog="wirestudio.targets.tasmota",
        description="Emit a Tasmota device template for a design.",
    )
    parser.add_argument("design", help="path to a design.json")
    args = parser.parse_args(argv)

    with open(args.design) as fh:
        design = Design.model_validate(json.load(fh))
    template, warnings = build_template(design, default_library())
    print(json.dumps(template))
    for w in warnings:
        print(f"warning: {w}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
