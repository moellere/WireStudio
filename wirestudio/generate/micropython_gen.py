"""Design -> MicroPython main.py.

The CircuitPython generator's twin over the `machine` API: each library
component carries a `micropython:` block with a Jinja2 `setup` fragment
(run once at boot) and an optional `loop` fragment (main while-loop
body); the generator resolves buses to `machine` objects, renders every
fragment with the component's wiring, and assembles one runnable file.
Pure function of design + library, like every other generator.

MicroPython names pins by bare GPIO number on every port, so fragments
use `Pin(n)` directly; no runtime lookup helper is needed. Buses are the
software implementations (`SoftI2C`, `SoftSPI`) because those accept
arbitrary pins on ESP32 and ESP8266 alike, where the hardware ids and
fixed pins differ per port.
"""
from __future__ import annotations

import ast

from jinja2 import Environment, StrictUndefined

from wirestudio.library import Library
from wirestudio.model import Design

_jinja = Environment(undefined=StrictUndefined, keep_trailing_newline=False)


class _Unsupported(Exception):
    """Raised from a fragment, through `unsupported(reason)`, for a variant
    it has no driver for; the component is skipped with `reason`."""


def _unsupported(reason: str) -> None:
    raise _Unsupported(reason)


_jinja.globals["unsupported"] = _unsupported

_BUS_VAR_PREFIX = {"i2c": "i2c", "spi": "spi", "uart": "uart", "1wire": "ow"}
_I2S_CLOCKS = {"LRCLK": "lrclk", "WS": "lrclk", "BCLK": "bclk"}


def _pin_num(pin: object) -> int | None:
    s = str(pin or "")
    digits = "".join(ch for ch in s if ch.isdigit())
    return int(digits) if s.startswith("GPIO") and digits else None


def _sanitize(name: str) -> str:
    out = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    return out if out and not out[0].isdigit() else f"b_{out}"


def generate_code(design: Design, library: Library) -> dict:
    """Return {"code": str, "deps": [str], "warnings": [str]}.

    Raises FileNotFoundError for an unknown board. Components without a
    `micropython:` block are skipped with a warning; the code still runs
    with everything that is mapped. `deps` are mip package specs.
    """
    board = library.board(design.board.library_id)
    warnings: list[str] = []
    deps: list[str] = []
    imports: set[str] = set()
    machine_names: set[str] = {"Pin"}
    setup_blocks: list[str] = []
    loop_blocks: list[str] = []

    bus_vars: dict[str, str] = {}
    bus_setup: dict[str, str] = {}
    used_bus_ids: set[str] = set()
    for bus in design.buses:
        if bus.type == "i2s":
            continue  # no bus object: each I2S part opens the peripheral on the bus's clock pins
        prefix = _BUS_VAR_PREFIX.get(bus.type)
        if prefix is None:
            warnings.append(f"bus {bus.id}: no MicroPython mapping for type '{bus.type}'")
            continue
        var = _sanitize(f"{prefix}_{bus.id}")
        if bus.type == "i2c":
            sda, scl = _pin_num(bus.sda), _pin_num(bus.scl)
            if sda is None or scl is None:
                warnings.append(f"bus {bus.id}: unassigned i2c pins; run Solve Pins")
                continue
            bus_setup[bus.id] = f"{var} = SoftI2C(scl=Pin({scl}), sda=Pin({sda}), freq=400000)"
        elif bus.type == "spi":
            clk, mosi, miso = _pin_num(bus.clk), _pin_num(bus.mosi), _pin_num(bus.miso)
            if clk is None:
                warnings.append(f"bus {bus.id}: unassigned spi clk; run Solve Pins")
                continue
            args = ["baudrate=1000000", "polarity=0", "phase=0", f"sck=Pin({clk})"]
            args.append(f"mosi=Pin({mosi})" if mosi is not None else "mosi=None")
            args.append(f"miso=Pin({miso})" if miso is not None else "miso=None")
            bus_setup[bus.id] = f"{var} = SoftSPI({', '.join(args)})"
        elif bus.type == "uart":
            tx, rx = _pin_num(bus.tx), _pin_num(bus.rx)
            if tx is None and rx is None:
                warnings.append(f"bus {bus.id}: unassigned uart pins; run Solve Pins")
                continue
            args = [f"baudrate={bus.baud_rate or 9600}"]
            if bus.parity in ("EVEN", "ODD"):
                args.append(f"parity={0 if bus.parity == 'EVEN' else 1}")
            if tx is not None:
                args.append(f"tx=Pin({tx})")
            if rx is not None:
                args.append(f"rx=Pin({rx})")
            bus_setup[bus.id] = f"{var} = UART(1, {', '.join(args)})"
            if board.chip_variant == "esp8266":
                warnings.append(f"bus {bus.id}: UART(1) on ESP8266 is transmit-only (GPIO2)")
        elif bus.type == "1wire":
            pin = _pin_num(bus.pin)
            if pin is None:
                warnings.append(f"bus {bus.id}: pin {bus.pin} is not a GPIO number" if bus.pin
                                else f"bus {bus.id}: unassigned 1-wire pin; run Solve Pins")
                continue
            bus_setup[bus.id] = f"{var} = onewire.OneWire(Pin({pin}))"
        bus_vars[bus.id] = var

    # A hub's helpers must exist before a child on it calls them.
    children = {c.component_id for c in design.connections if c.target.kind == "component"}
    rendered: set[str] = set()
    for comp in sorted(design.components, key=lambda c: c.id in children):
        lib_comp = library.component(comp.library_id)
        spec = lib_comp.micropython
        if spec is None:
            warnings.append(
                f"{comp.id} ({comp.library_id}): no MicroPython driver mapping; skipped"
            )
            continue

        pins: dict[str, int] = {}
        bus_var = None
        bus_dump = None
        comp_bus_ids: set[str] = set()
        parent = None
        skip = None
        for conn in design.connections:
            if conn.component_id != comp.id:
                continue
            t = conn.target
            if t.kind == "gpio" and t.pin:
                num = _pin_num(t.pin)
                if num is None:
                    skip = f"{comp.id}.{conn.pin_role}: pin {t.pin} is not a GPIO number"
                else:
                    pins[conn.pin_role] = num
            elif t.kind == "bus":
                i2s = next((b for b in design.buses if b.id == t.bus_id and b.type == "i2s"), None)
                if i2s is not None:
                    field = _I2S_CLOCKS.get(conn.pin_role)
                    num = _pin_num(getattr(i2s, field)) if field else None
                    if num is not None:
                        pins[conn.pin_role] = num
                    elif field:
                        skip = f"{comp.id}.{conn.pin_role}: i2s bus {i2s.id} has no {field} pin; run Solve Pins"
                    else:
                        skip = f"{comp.id}.{conn.pin_role}: an i2s bus carries only the clocks; wire it to a GPIO"
                    continue
                bus_var = bus_vars.get(t.bus_id or "")
                if bus_var and t.bus_id:
                    comp_bus_ids.add(t.bus_id)
                for b in design.buses:
                    if b.id == t.bus_id:
                        bus_dump = b.model_dump()
            elif t.kind == "component":
                parent = t.component_id
            elif t.kind == "expander_pin":
                skip = f"{comp.id}.{conn.pin_role}: expander pins have no MicroPython path"
        if parent is None and any(p.kind == "hub_ref" for p in lib_comp.electrical.pins):
            skip = f"{comp.id}: not connected to its hub"
        elif parent is not None and parent not in rendered:
            skip = f"{comp.id}: its hub {parent} is not set up"
        if skip:
            warnings.append(f"{skip}; skipped")
            continue

        ctx = {
            "id": _sanitize(comp.id),
            "label": comp.label,
            "params": dict(comp.params or {}),
            "pins": pins,
            "bus": bus_dump,
            "bus_var": bus_var,
            "parent": _sanitize(parent) if parent else None,
            "board": board,
        }
        try:
            setup = _jinja.from_string(spec.setup).render(**ctx).strip("\n")
        except _Unsupported as e:
            warnings.append(f"{comp.id} ({comp.library_id}): {e}; skipped")
            continue
        except Exception as e:
            warnings.append(f"{comp.id}: fragment failed to render ({e}); skipped")
            continue
        used_bus_ids |= comp_bus_ids
        rendered.add(comp.id)
        setup_blocks.append(f"# {comp.label or comp.id} ({comp.library_id})\n{setup}")
        if spec.loop:
            loop = _jinja.from_string(spec.loop).render(**ctx).strip("\n")
            if loop:
                loop_blocks.append(loop)
        for d in spec.deps:
            if d not in deps:
                deps.append(d)
        for imp in spec.imports:
            if imp.startswith("from machine import "):
                machine_names.update(n.strip() for n in imp.removeprefix("from machine import ").split(","))
            else:
                imports.add(imp)

    emitted = [b for b in design.buses if b.id in bus_setup and b.id in used_bus_ids]
    emitted_buses = [bus_setup[b.id] for b in emitted]
    for b in emitted:
        if b.type == "1wire":
            imports.add("import onewire")
        else:
            machine_names.add(bus_setup[b.id].split(" = ", 1)[1].split("(", 1)[0])
    lines: list[str] = [
        f'"""{design.name or design.id} -- generated by wirestudio."""',
    ]
    if deps:
        lines += [
            "# Drivers to install once, with the board online (or `mpremote mip install <spec>`):",
            *[f"#   mip.install({d!r})" for d in sorted(deps)],
        ]
    if warnings:
        lines += ["# Not generated (no MicroPython mapping):",
                  *[f"#   {w}" for w in warnings]]
    lines += ["", "import time", "", f"from machine import {', '.join(sorted(machine_names))}"]
    for imp in sorted(imports):
        lines.append(imp)
    lines.append("")
    if emitted_buses:
        lines += ["", "# Buses", *emitted_buses]
    for block in setup_blocks:
        lines += ["", block]
    lines += ["", "", "while True:"]
    if loop_blocks:
        for block in loop_blocks:
            lines += [f"    {ln}" if ln else "" for ln in block.split("\n")]
    else:
        lines.append('    print("alive")')
    lines += ["    time.sleep(5)", ""]

    code = "\n".join(lines)
    ast.parse(code)  # a fragment that breaks the file is a library bug
    return {"code": code, "deps": sorted(deps), "warnings": warnings}
