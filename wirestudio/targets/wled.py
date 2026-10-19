"""WLED target: emit the hardware section of `cfg.json` from a solved design.

WLED splits its hardware into two tiers. LED outputs, buttons, the IR
receiver, the relay and the bus pins are runtime settings: the stock
release image reads them from `cfg.json` at boot, so a design made of
those parts needs no build. Sensors and most other peripherals are
usermods, compiled in with a `-D USERMOD_X` build flag; that tier is a
custom PlatformIO build and is not covered here yet.

This module is the runtime tier: a pure mapping, no toolchain. Library
components opt in with a `wled:` block naming the kind of hardware they
are and the pin roles WLED reads, and the generator writes the `hw`
object WLED's `cfg.cpp` deserialises (keys and type codes from
`wled00/const.h` and `wled00/cfg.cpp`). Upload the file as `cfg.json`
through the WLED UI's backup / restore, or paste the LED outputs by
hand; the device reboots into the design's wiring.

CLI: `python -m wirestudio.targets.wled <design.json>` prints the
config; warnings go to stderr.
"""
from __future__ import annotations

import json
import sys
from typing import Optional

from wirestudio.library import Library
from wirestudio.model import Design, DesignWarning
from wirestudio.targets.base import TargetPlugin, register
from wirestudio.targets.tasmota import pin_number

# COL_ORDER_* from const.h.
COLOR_ORDER = {"GRB": 0, "RGB": 1, "BRG": 2, "RBG": 3, "BGR": 4, "GBR": 5}

# BTN_TYPE_* from const.h, the ones a library block may name.
BUTTON_TYPES = {"push": 2, "push_act_high": 3, "switch": 4, "pir": 5, "touch": 6}

# Chips WLED publishes release images for. The C6 has no build yet.
_CHIPS = {"esp8266", "esp8285", "esp32", "esp32s2", "esp32s3", "esp32c3"}

# WLED_MAX_BUTTONS and the digital output channels per chip, const.h.
_MAX_BUTTONS = {"esp8266": 2, "esp8285": 2}
_MAX_OUTPUTS = {"esp8266": 3, "esp8285": 3, "esp32": 8, "esp32s2": 4, "esp32s3": 4, "esp32c3": 2}


def _gpio(design: Design, comp_id: str, role: str) -> Optional[str]:
    for c in design.connections:
        if c.component_id == comp_id and c.pin_role == role and c.target.kind == "gpio":
            return c.target.pin
    return None


def build_cfg(design: Design, library: Library) -> tuple[dict, list[str]]:
    """The `cfg.json` document (its `hw` object) plus warnings for what
    the design contains that the runtime tier cannot express."""
    board = library.board(design.board.library_id)
    chip = board.chip_variant
    if chip not in _CHIPS:
        raise ValueError(f"WLED has no release image for chip '{chip}'")

    warnings: list[str] = []
    outputs: list[dict] = []
    buttons: list[dict] = []
    ir: Optional[dict] = None
    relay: Optional[dict] = None
    max_buttons = _MAX_BUTTONS.get(chip, 10)
    max_outputs = _MAX_OUTPUTS[chip]

    def pins_for(comp, spec) -> Optional[list[int]]:
        numbers = []
        for role in spec.pins:
            pin = _gpio(design, comp.id, role)
            num = pin_number(pin) if pin else None
            if num is None:
                warnings.append(f"{comp.id}.{role}: not wired to a GPIO; skipped")
                return None
            numbers.append(num)
        return numbers

    for comp in design.components:
        lib_comp = library.component(comp.library_id)
        spec = lib_comp.wled
        if spec is None:
            warnings.append(f"{comp.id} ({comp.library_id}): no WLED mapping; not in cfg.json")
            continue
        params = comp.params or {}
        pins = pins_for(comp, spec)
        if pins is None:
            continue

        if spec.kind == "led":
            if len(outputs) >= max_outputs:
                warnings.append(f"{comp.id}: more than {max_outputs} LED outputs on {chip}; skipped")
                continue
            led_type = spec.type
            if spec.chipset_param:
                chipset = str(params.get(spec.chipset_param, "") or "")
                if chipset:
                    if chipset in spec.chipsets:
                        led_type = spec.chipsets[chipset]
                    else:
                        warnings.append(
                            f"{comp.id}: chipset {chipset!r} has no WLED bus type; using the "
                            f"{lib_comp.id} default ({spec.type})")
            order = 0
            if spec.order_param:
                raw = str(params.get(spec.order_param, "") or "GRB").upper()
                base = raw.replace("W", "")
                if base in COLOR_ORDER:
                    order = COLOR_ORDER[base]
                else:
                    warnings.append(f"{comp.id}: colour order {raw!r} is not one WLED knows; using GRB")
            length = int(params.get(spec.length_param, 1) or 1)
            start = sum(o["len"] for o in outputs)
            outputs.append({
                "start": start, "len": length, "pin": pins, "order": order,
                "rev": False, "skip": 0, "type": led_type, "ref": False,
            })
        elif spec.kind == "button":
            if len(buttons) >= max_buttons:
                warnings.append(f"{comp.id}: more than {max_buttons} buttons on {chip}; skipped")
                continue
            buttons.append({"type": BUTTON_TYPES[spec.button], "pin": pins, "macros": [0, 0, 0]})
        elif spec.kind == "ir":
            if ir is not None:
                warnings.append(f"{comp.id}: WLED has one IR receiver; skipped")
                continue
            # type 0 leaves the remote layout to the LED settings page;
            # the pin is allocated regardless.
            ir = {"pin": pins[0], "type": 0, "sel": True}
            warnings.append(f"{comp.id}: pick the remote layout under LED settings > IR remote")
        elif spec.kind == "relay":
            if relay is not None:
                warnings.append(f"{comp.id}: WLED has one relay pin; a second needs the multi_relay usermod")
                continue
            relay = {"pin": pins[0], "rev": False, "odrain": False}

    hw: dict = {
        "led": {"total": sum(o["len"] for o in outputs), "ins": outputs},
        "btn": {"ins": buttons},
    }
    if ir is not None:
        hw["ir"] = ir
    if relay is not None:
        hw["relay"] = relay
    interfaces: dict = {}
    i2c = next((b for b in design.buses if b.type == "i2c" and b.sda and b.scl), None)
    if i2c is not None:
        interfaces["i2c-pin"] = [pin_number(i2c.sda), pin_number(i2c.scl)]
    spi = next((b for b in design.buses if b.type == "spi" and b.mosi and b.clk), None)
    if spi is not None:
        interfaces["spi-pin"] = [pin_number(spi.mosi), pin_number(spi.clk),
                                 pin_number(spi.miso) if spi.miso else -1]
    if interfaces:
        hw["if"] = interfaces
    if not outputs:
        warnings.append("no LED output: WLED will boot with its default strip on GPIO2")
    return {"hw": hw}, warnings


class WledTarget(TargetPlugin):
    """Emit WLED's cfg.json hardware section. Pure mapping; no build step."""

    id = "wled"

    def board_ids(self, library: Library) -> list[str]:
        return sorted(b.id for b in library.list_boards() if b.chip_variant in _CHIPS)

    def component_ids(self, library: Library) -> list[str]:
        return sorted(c.id for c in library.list_components() if c.wled is not None)

    def generate(self, design: Design, library: Library) -> dict[str, str]:
        cfg, warnings = build_cfg(design, library)
        files = {"cfg.json": json.dumps(cfg, indent=2) + "\n"}
        if warnings:
            files["cfg-warnings.txt"] = "\n".join(warnings) + "\n"
        return files

    def validate(self, design: Design, library: Library) -> list[DesignWarning]:
        try:
            _, warnings = build_cfg(design, library)
        except (ValueError, FileNotFoundError):
            return []
        return [DesignWarning(level="info", code="wled_unmapped", text=w) for w in warnings]

    def router(self, library: Library):
        from fastapi import APIRouter, HTTPException

        router = APIRouter(tags=["wled"])

        @router.post("/cfg")
        def wled_cfg(design: dict) -> dict:
            d = Design.model_validate(design)
            try:
                cfg, warnings = build_cfg(d, library)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e)) from e
            except FileNotFoundError as e:
                raise HTTPException(status_code=404, detail=str(e)) from e
            return {"cfg": cfg, "warnings": warnings}

        return router


# Under `python -m wirestudio.targets.wled` runpy executes this module
# body a second time after the package import already registered it.
try:
    register(WledTarget())
except ValueError:
    pass


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    from wirestudio.library import default_library

    parser = argparse.ArgumentParser(
        prog="wirestudio.targets.wled",
        description="Emit WLED's cfg.json hardware section for a design.",
    )
    parser.add_argument("design", help="path to a design.json")
    args = parser.parse_args(argv)

    with open(args.design) as fh:
        design = Design.model_validate(json.load(fh))
    cfg, warnings = build_cfg(design, default_library())
    print(json.dumps(cfg, indent=2))
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
