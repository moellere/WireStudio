from __future__ import annotations

import textwrap

from wirestudio.library import Library
from wirestudio.model import Bus, Design


def _bus_signal(bus: Bus, role: str) -> str | None:
    # UART is crossed: peripheral TX pin physically wires to the MCU's RX pin
    # (bus.rx), and the peripheral RX wires to the MCU's TX (bus.tx).
    table: dict[str, dict[str, str | None]] = {
        "i2c":  {"SDA": bus.sda, "SCL": bus.scl},
        "spi":  {"CLK": bus.clk, "SCK": bus.clk, "MISO": bus.miso, "MOSI": bus.mosi},
        "i2s":  {"LRCLK": bus.lrclk, "BCLK": bus.bclk},
        "uart": {"RX": bus.tx, "TX": bus.rx},
    }
    return table.get(bus.type, {}).get(role)


def _box(title: str, lines: list[str]) -> str:
    inner = max([len(title)] + [len(line) for line in lines])
    border = "+" + "-" * (inner + 4) + "+"
    out = [border, f"|  {title.ljust(inner)}  |", border]
    for line in lines:
        out.append(f"|  {line.ljust(inner)}  |")
    out.append(border)
    return "\n".join(out)


def render_ascii(design: Design, library: Library) -> str:
    board = library.board(design.board.library_id)
    title = f"{board.name}  ---  {design.id}"
    lines: list[str] = []

    rails = ", ".join(r.name for r in board.rails)
    lines.append(f"Rails: {rails}")
    lines.append("")

    for comp in design.components:
        lib_comp = library.component(comp.library_id)
        lines.append(f"{comp.id}  [{lib_comp.name}]  -- {comp.label}")
        for conn in (c for c in design.connections if c.component_id == comp.id):
            t = conn.target
            if t.kind == "gpio":
                lines.append(f"  {conn.pin_role:<5} -> {t.pin}")
            elif t.kind == "rail":
                lines.append(f"  {conn.pin_role:<5} -> rail {t.rail}")
            elif t.kind == "bus":
                bus = next((b for b in design.buses if b.id == t.bus_id), None)
                if bus is None:
                    lines.append(f"  {conn.pin_role:<5} -> bus {t.bus_id}")
                else:
                    signal = _bus_signal(bus, conn.pin_role)
                    if signal:
                        lines.append(f"  {conn.pin_role:<5} -> {bus.id} ({signal})")
                    else:
                        lines.append(f"  {conn.pin_role:<5} -> {bus.id} ({bus.type})")
            elif t.kind == "expander_pin":
                mode = f" {t.mode}" if t.mode else ""
                inv = " inverted" if t.inverted else ""
                lines.append(f"  {conn.pin_role:<5} -> {t.expander_id}.{t.number}{mode}{inv}")
        lines.append("")

    if design.passives:
        lines.append("Passives:")
        for p in design.passives:
            between = "  <->  ".join(p.between)
            note = f"   ({p.purpose})" if p.purpose else ""
            lines.append(f"  {p.id}: {p.value} {p.kind}, {between}{note}")
        lines.append("")

    lines.append("BOM:")
    lines.append(f"  - {board.name}")
    for comp in design.components:
        lib_comp = library.component(comp.library_id)
        lines.append(f"  - {lib_comp.name}  ({comp.id})")
    pcounts: dict[str, int] = {}
    for p in design.passives:
        key = f"{p.value} {p.kind}"
        pcounts[key] = pcounts.get(key, 0) + 1
    for k, n in pcounts.items():
        lines.append(f"  - {n}x {k}")

    if design.power.budget_ma:
        peak = sum(
            (library.component(c.library_id).electrical.current_ma_peak or 0)
            for c in design.components
        )
        typ = sum(
            (library.component(c.library_id).electrical.current_ma_typical or 0)
            for c in design.components
        )
        status = "OK" if peak <= design.power.budget_ma else "OVER BUDGET"
        lines.append("")
        lines.append(
            f"Power: ~{int(typ)}mA typical, ~{int(peak)}mA peak (budget {design.power.budget_ma}mA)  {status}"
        )

    if design.warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in design.warnings:
            head = f"  [{w.level}] {w.code}: "
            wrapped = textwrap.wrap(w.text, width=80) or [""]
            lines.append(head + wrapped[0])
            indent = " " * len(head)
            for cont in wrapped[1:]:
                lines.append(indent + cont)
    else:
        lines.append("")
        lines.append("Warnings: none")

    return _box(title, lines)
