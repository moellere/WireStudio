from __future__ import annotations

from studio.library import Library
from studio.model import Design


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
                if bus and bus.type == "i2c":
                    pin = bus.sda if conn.pin_role == "SDA" else bus.scl if conn.pin_role == "SCL" else "?"
                    lines.append(f"  {conn.pin_role:<5} -> {bus.id} ({pin})")
                elif bus and bus.type == "spi":
                    pin_map = {"CLK": bus.clk, "MISO": bus.miso, "MOSI": bus.mosi, "SCK": bus.clk}
                    pin = pin_map.get(conn.pin_role, "?")
                    lines.append(f"  {conn.pin_role:<5} -> {bus.id} ({pin})")
                elif bus and bus.type == "i2s":
                    pin_map = {"LRCLK": bus.lrclk, "BCLK": bus.bclk}
                    pin = pin_map.get(conn.pin_role, "?")
                    lines.append(f"  {conn.pin_role:<5} -> {bus.id} ({pin})")
                else:
                    lines.append(f"  {conn.pin_role:<5} -> bus {t.bus_id}")
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
            lines.append(f"  [{w.level}] {w.code}: {w.text}")
    else:
        lines.append("")
        lines.append("Warnings: none")

    return _box(title, lines)
