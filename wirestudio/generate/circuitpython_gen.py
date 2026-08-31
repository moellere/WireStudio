"""Design -> CircuitPython code.py.

The LoRaWAN-fragment pattern applied to Python: each library component
carries a `circuitpython:` block with a Jinja2 `setup` fragment (run
once at boot) and an optional `loop` fragment (main while-loop body);
the generator resolves buses to busio objects, renders every fragment
with the component's wiring, and assembles one runnable file. Pure
function of design + library, like every other generator.

Pin objects go through the P() helper emitted into the file: builds
name the same GPIO `IO21`, `GPIO21` or `D21` depending on the port, so
fragments reference bare numbers and P() resolves at runtime.
"""
from __future__ import annotations

import ast

from jinja2 import Environment, StrictUndefined

from wirestudio.library import Library
from wirestudio.model import Design

_jinja = Environment(undefined=StrictUndefined, keep_trailing_newline=False)

_BUS_VAR_PREFIX = {"i2c": "i2c", "spi": "spi", "uart": "uart"}


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
    `circuitpython:` block are skipped with a warning; the code still
    runs with everything that is mapped.
    """
    library.board(design.board.library_id)  # unknown board raises here
    warnings: list[str] = []
    deps: list[str] = []
    imports: set[str] = set()
    setup_blocks: list[str] = []
    loop_blocks: list[str] = []

    bus_vars: dict[str, str] = {}
    bus_setup: dict[str, str] = {}
    used_bus_ids: set[str] = set()
    for bus in design.buses:
        prefix = _BUS_VAR_PREFIX.get(bus.type)
        if prefix is None:
            warnings.append(f"bus {bus.id}: no CircuitPython mapping for type '{bus.type}'")
            continue
        var = _sanitize(f"{prefix}_{bus.id}")
        if bus.type == "i2c":
            sda, scl = _pin_num(bus.sda), _pin_num(bus.scl)
            if sda is None or scl is None:
                warnings.append(f"bus {bus.id}: unassigned i2c pins; run Solve Pins")
                continue
            bus_setup[bus.id] = f"{var} = busio.I2C(P({scl}), P({sda}))"
        elif bus.type == "spi":
            clk, mosi, miso = _pin_num(bus.clk), _pin_num(bus.mosi), _pin_num(bus.miso)
            if clk is None:
                warnings.append(f"bus {bus.id}: unassigned spi clk; run Solve Pins")
                continue
            args = [f"P({clk})"]
            args.append(f"MOSI=P({mosi})" if mosi is not None else "MOSI=None")
            args.append(f"MISO=P({miso})" if miso is not None else "MISO=None")
            bus_setup[bus.id] = f"{var} = busio.SPI({', '.join(args)})"
        elif bus.type == "uart":
            tx, rx = _pin_num(bus.tx), _pin_num(bus.rx)
            if tx is None and rx is None:
                warnings.append(f"bus {bus.id}: unassigned uart pins; run Solve Pins")
                continue
            args = [
                f"TX=P({tx})" if tx is not None else "TX=None",
                f"RX=P({rx})" if rx is not None else "RX=None",
                f"baudrate={bus.baud_rate or 9600}",
            ]
            bus_setup[bus.id] = f"{var} = busio.UART({', '.join(args)})"
        bus_vars[bus.id] = var

    for comp in design.components:
        lib_comp = library.component(comp.library_id)
        spec = lib_comp.circuitpython
        if spec is None:
            warnings.append(
                f"{comp.id} ({comp.library_id}): no CircuitPython driver mapping; skipped"
            )
            continue

        pins: dict[str, int] = {}
        bus_var = None
        bus_dump = None
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
                bus_var = bus_vars.get(t.bus_id or "")
                if bus_var and t.bus_id:
                    used_bus_ids.add(t.bus_id)
                for b in design.buses:
                    if b.id == t.bus_id:
                        bus_dump = b.model_dump()
            elif t.kind == "expander_pin":
                skip = f"{comp.id}.{conn.pin_role}: expander pins have no CircuitPython path"
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
        }
        try:
            setup = _jinja.from_string(spec.setup).render(**ctx).strip("\n")
        except Exception as e:
            warnings.append(f"{comp.id}: fragment failed to render ({e}); skipped")
            continue
        setup_blocks.append(f"# {comp.label or comp.id} ({comp.library_id})\n{setup}")
        if spec.loop:
            loop = _jinja.from_string(spec.loop).render(**ctx).strip("\n")
            if loop:
                loop_blocks.append(loop)
        for d in spec.deps:
            if d not in deps:
                deps.append(d)
        imports.update(spec.imports)

    emitted_buses = [bus_setup[b] for b in bus_setup if b in used_bus_ids]
    needs_busio = bool(emitted_buses)
    lines: list[str] = [
        f'"""{design.name or design.id} -- generated by wirestudio."""',
    ]
    if deps:
        lines += [
            "# Copy these Adafruit bundle libraries into CIRCUITPY/lib:",
            *[f"#   {d}" for d in sorted(deps)],
        ]
    if warnings:
        lines += ["# Not generated (no CircuitPython mapping):",
                  *[f"#   {w}" for w in warnings]]
    lines += ["", "import time", "", "import board"]
    if needs_busio:
        lines.append("import busio")
    for imp in sorted(imports):
        lines.append(imp)
    lines += [
        "",
        "",
        "def find_pin(*names):",
        "    for n in names:",
        "        p = getattr(board, n, None)",
        "        if p is not None:",
        "            return p",
        '    raise AttributeError("none of %s on this build" % (names,))',
        "",
        "",
        "def P(n):",
        '    return find_pin("IO%d" % n, "GPIO%d" % n, "D%d" % n)',
        "",
    ]
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
