"""WLED target: `cfg.json` from a solved design, and the usermod build.

WLED splits its hardware into two tiers. LED outputs, buttons, the IR
receiver, the relay and the bus pins are runtime settings: the stock
release image reads them from `cfg.json` at boot, so a design made of
those parts needs no build. Sensors and most other peripherals are
usermods, compiled in with a `-D USERMOD_X` build flag in a PlatformIO
environment; a design that carries one is a custom build of the pinned
release, with the usermod's own settings riding `cfg.json`'s `um`
section.

Library components opt in with a `wled:` block naming the kind of
hardware they are and the pin roles WLED reads. `build_cfg` writes the
`hw` object WLED's `cfg.cpp` deserialises (keys and type codes from
`wled00/const.h` and `wled00/cfg.cpp`) plus `um` for the usermods;
`build_platformio_override` writes the environment that compiles those
usermods into `WLED_RELEASE`, in that release's form (build flags and
`lib_deps`; the next release names usermods with `custom_usermods`
instead). `wled_build` runs the build.

CLI: `python -m wirestudio.targets.wled <design.json>` prints the
config, `--override` the environment; warnings go to stderr.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Optional

from wirestudio.library import Library
from wirestudio.model import Design, DesignWarning
from wirestudio.targets.base import TargetPlugin, register
from wirestudio.targets.tasmota import pin_number

WLED_RELEASE = "v0.15.2"

# COL_ORDER_* from const.h.
COLOR_ORDER = {"GRB": 0, "RGB": 1, "BRG": 2, "RBG": 3, "BGR": 4, "GBR": 5}

# BTN_TYPE_* from const.h, the ones a library block may name.
BUTTON_TYPES = {"push": 2, "push_act_high": 3, "switch": 4, "pir": 5, "touch": 6}

# Chips WLED publishes release images for. The C6 has no build yet.
_CHIPS = {"esp8266", "esp8285", "esp32", "esp32s2", "esp32s3", "esp32c3"}

# WLED_MAX_BUTTONS and the digital output channels per chip, const.h.
_MAX_BUTTONS = {"esp8266": 2, "esp8285": 2}
_MAX_OUTPUTS = {"esp8266": 3, "esp8285": 3, "esp32": 8, "esp32s2": 4, "esp32s3": 4, "esp32c3": 2}

# The release's own environment per chip (platformio.ini at WLED_RELEASE);
# the override environment extends it and appends the usermod flags.
_BASE_ENV = {
    "esp8266": "nodemcuv2", "esp8285": "esp8266_2m", "esp32": "esp32dev",
    "esp32s2": "lolin_s2_mini", "esp32s3": "esp32s3dev_8MB_opi", "esp32c3": "esp32c3dev",
}

_KEY_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,127}$")


def _gpio(design: Design, comp_id: str, role: str) -> Optional[str]:
    """The GPIO a pin role lands on: wired directly, or through a 1-wire
    bus, whose single pin is the GPIO."""
    buses = {b.id: b for b in design.buses}
    for c in design.connections:
        if c.component_id != comp_id or c.pin_role != role:
            continue
        if c.target.kind == "gpio":
            return c.target.pin
        if c.target.kind == "bus":
            bus = buses.get(c.target.bus_id)
            if bus is not None and bus.type == "1wire":
                return bus.pin
    return None


def _as_int(value) -> Optional[int]:
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None


def build_cfg(design: Design, library: Library) -> tuple[dict, list[str]]:
    """The `cfg.json` document (`hw`, and `um` when the design has
    usermods) plus warnings for what the design contains that WLED
    cannot express."""
    board = library.board(design.board.library_id)
    chip = board.chip_variant
    if chip not in _CHIPS:
        raise ValueError(f"WLED has no release image for chip '{chip}'")

    warnings: list[str] = []
    outputs: list[dict] = []
    buttons: list[dict] = []
    ir: Optional[dict] = None
    relay: Optional[dict] = None
    usermods: dict[str, dict] = {}
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
        elif spec.kind == "usermod" and spec.um_name:
            if spec.um_name in usermods:
                warnings.append(
                    f"{comp.id}: the {spec.usermod} usermod runs once; its settings come from the "
                    f"first {lib_comp.id}")
                continue
            entry = dict(spec.um)
            for role, key in spec.um_pins.items():
                entry[key] = pins[spec.pins.index(role)]
            for key, param in spec.um_params.items():
                value = params.get(param)
                if value is not None:
                    number = _as_int(value)
                    entry[key] = value if number is None else number
            usermods[spec.um_name] = entry

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
    cfg: dict = {"hw": hw}
    if usermods:
        cfg["um"] = usermods
    return cfg, warnings


def build_platformio_override(design: Design, library: Library) -> tuple[Optional[str], list[str]]:
    """The `platformio_override.ini` environment that compiles the design's
    usermods into WLED_RELEASE, or None when the design has none and the
    release image serves as is."""
    board = library.board(design.board.library_id)
    chip = board.chip_variant
    if chip not in _BASE_ENV:
        raise ValueError(f"WLED has no release image for chip '{chip}'")
    warnings: list[str] = []
    flags: list[str] = []
    libs: list[str] = []
    seen: set[str] = set()
    for comp in design.components:
        lib_comp = library.component(comp.library_id)
        spec = lib_comp.wled
        if spec is None or spec.kind != "usermod":
            continue
        if spec.define in seen:
            warnings.append(
                f"{comp.id}: the {spec.usermod} usermod is compiled in once; its pins come from "
                f"the first {lib_comp.id}")
            continue
        seen.add(spec.define)
        flags.append(f"-D {spec.define}")
        for role, define in spec.pin_defines.items():
            pin = _gpio(design, comp.id, role)
            num = pin_number(pin) if pin else None
            if num is None:
                warnings.append(f"{comp.id}.{role}: not wired to a GPIO; {define} left at the usermod default")
                continue
            flags.append(f"-D {define}={num}")
        params = comp.params or {}
        for param, pd in spec.param_defines.items():
            value = params.get(param)
            if value is None:
                continue
            mapped = pd.values.get(str(value), value) if not pd.values else pd.values.get(str(value))
            if mapped is None:
                warnings.append(f"{comp.id}: {param}={value!r} has no {pd.define} value; usermod default used")
                continue
            flags.append(f"-D {pd.define}={mapped}")
        for dep in spec.lib_deps:
            if dep not in libs:
                libs.append(dep)
    if not flags:
        return None, warnings
    base = _BASE_ENV[chip]
    if chip == "esp32s3":
        warnings.append(
            f"esp32s3: the override extends env:{base} (8MB flash, OPI PSRAM); "
            "an S3 module with other memory needs another WLED environment")
    lines = [
        f"; wirestudio: {design.id} on WLED {WLED_RELEASE}",
        "[env:wirestudio]",
        f"extends = env:{base}",
        f"build_flags = ${{env:{base}.build_flags}}",
        *(f"  {flag}" for flag in flags),
    ]
    if libs:
        lines += [f"lib_deps = ${{env:{base}.lib_deps}}", *(f"  {dep}" for dep in libs)]
    return "\n".join(lines) + "\n", warnings


class WledTarget(TargetPlugin):
    """Emit WLED's cfg.json, and the override environment for its usermods."""

    id = "wled"

    def board_ids(self, library: Library) -> list[str]:
        return sorted(b.id for b in library.list_boards() if b.chip_variant in _CHIPS)

    def component_ids(self, library: Library) -> list[str]:
        return sorted(c.id for c in library.list_components() if c.wled is not None)

    def generate(self, design: Design, library: Library) -> dict[str, str]:
        cfg, warnings = build_cfg(design, library)
        override, more = build_platformio_override(design, library)
        files = {"cfg.json": json.dumps(cfg, indent=2) + "\n"}
        if override is not None:
            files["platformio_override.ini"] = override
        warnings = list(dict.fromkeys(warnings + more))
        if warnings:
            files["cfg-warnings.txt"] = "\n".join(warnings) + "\n"
        return files

    def validate(self, design: Design, library: Library) -> list[DesignWarning]:
        try:
            _, warnings = build_cfg(design, library)
            _, more = build_platformio_override(design, library)
        except (ValueError, FileNotFoundError):
            return []
        return [DesignWarning(level="info", code="wled_unmapped", text=w)
                for w in dict.fromkeys(warnings + more)]

    def build_backend(self):
        from wirestudio.targets.wled_build import LocalWledBackend

        return LocalWledBackend()

    def router(self, library: Library):
        from fastapi import APIRouter, HTTPException, Response
        from fastapi.responses import StreamingResponse
        from pydantic import ValidationError

        from wirestudio.targets.build_backend import BuildUnavailable

        router = APIRouter(tags=["wled"])
        backend = self.build_backend()

        def _design(design: dict) -> Design:
            try:
                return Design.model_validate(design)
            except ValidationError as exc:
                raise HTTPException(status_code=422, detail=exc.errors()) from exc

        @router.post("/cfg")
        def wled_cfg(design: dict) -> dict:
            d = _design(design)
            try:
                cfg, warnings = build_cfg(d, library)
                override, more = build_platformio_override(d, library)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e)) from e
            except FileNotFoundError as e:
                raise HTTPException(status_code=404, detail=str(e)) from e
            return {"cfg": cfg, "platformio_override": override,
                    "warnings": list(dict.fromkeys(warnings + more))}

        @router.get("/compile/status")
        def compile_status() -> dict:
            return backend.status()

        # No return annotations on the response-returning routes: with
        # `from __future__ import annotations` they are strings OpenAPI
        # generation cannot resolve for the locally imported classes.
        @router.post("/compile")
        def compile(design: dict):
            """Build the release with the design's usermods, streaming the
            build log as SSE. A design without usermods is refused: the
            release image is the firmware, and cfg.json carries the rest."""
            d = _design(design)
            try:
                override, _ = build_platformio_override(d, library)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e)) from e
            except FileNotFoundError as e:
                raise HTTPException(status_code=404, detail=str(e)) from e
            if override is None:
                raise HTTPException(
                    status_code=422,
                    detail="design has no usermods; flash the WLED release image and upload cfg.json")
            job_id = backend.enqueue(d, library)

            def events():
                try:
                    for event in backend.stream(job_id, d, library):
                        yield f"data: {json.dumps(event)}\n\n"
                except BuildUnavailable as exc:
                    yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"

            return StreamingResponse(events(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        @router.get("/firmware/{job_id}")
        def firmware(job_id: str, factory: bool = False):
            if not _KEY_RE.match(job_id):
                raise HTTPException(status_code=404, detail="unknown firmware")
            data = backend.artifact(job_id, "factory.bin" if factory else "firmware.bin")
            if data is None:
                raise HTTPException(status_code=404, detail="firmware not built; POST /wled/compile first")
            return Response(content=data, media_type="application/octet-stream",
                            headers={"Content-Disposition": f'attachment; filename="{job_id}.bin"'})

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
        description="Emit WLED's cfg.json, or the platformio_override.ini for its usermods.",
    )
    parser.add_argument("design", help="path to a design.json")
    parser.add_argument("--override", action="store_true",
                        help="print the platformio_override.ini environment instead of cfg.json")
    args = parser.parse_args(argv)

    with open(args.design) as fh:
        design = Design.model_validate(json.load(fh))
    library = default_library()
    if args.override:
        text, warnings = build_platformio_override(design, library)
        if text is None:
            print("design has no usermods; the release image needs no build", file=sys.stderr)
            return 1
        sys.stdout.write(text)
    else:
        cfg, warnings = build_cfg(design, library)
        print(json.dumps(cfg, indent=2))
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
