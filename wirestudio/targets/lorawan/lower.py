"""Lower the standalone path's `lorawan.gps` / `dht22` / `oled` blocks to the
library components they stand for.

The blocks predate per-component `lorawan:` codegen: a design asked for a
GPS by naming two pins under `lorawan.gps` and the firmware generator
hardcoded the rest. Today `uart_gps`, `dht` and `ssd1306` carry their own
fragments, so the three blocks are sugar for a component, a bus and a few
connections. Everything downstream of this module reads only
`design.components` / `buses` / `connections`; the blocks stay accepted
on input until the 1.0 migrator rewrites them.
"""
from __future__ import annotations

from wirestudio.library import Library
from wirestudio.model import Bus, Component, Connection, Design

SUGAR_FIELDS = ("gps", "dht22", "oled")

# Instance ids match what the codec used to synthesize, so device-profile
# names and the C++ singletons a lowered design produces are the ones a
# device provisioned from the same design already carries.
_GPS_ID, _DHT_ID, _OLED_ID = "gps", "dht1", "oled"


def sugar_in_use(design: Design) -> list[str]:
    """Which of the deprecated blocks the design sets."""
    lw = design.lorawan
    if lw is None:
        return []
    return [f for f in SUGAR_FIELDS if getattr(lw, f) is not None]


def lower_lorawan_sugar(design: Design, library: Library) -> Design:
    """A copy of `design` with each sugar block replaced by the component it
    names, wired the way a user would have wired it, and the block cleared.
    A design without sugar is returned as is. A block whose component the
    design already carries (by library id) is dropped rather than doubled.
    Idempotent."""
    fields = sugar_in_use(design)
    if not fields:
        return design
    try:
        board = library.board(design.board.library_id)
    except FileNotFoundError:
        board = None
    rails = {r.name for r in board.rails} if board else set()
    onboard = (board.onboard_peripherals or {}) if board else {}
    i2c_default = (board.default_buses or {}).get("i2c", {}) if board else {}

    out = design.model_copy(deep=True)
    present = {c.library_id for c in out.components}
    ids = {c.id for c in out.components} | {b.id for b in out.buses}

    def unique(base: str) -> str:
        if base not in ids:
            ids.add(base)
            return base
        n = 2
        while f"{base}{n}" in ids:
            n += 1
        ids.add(f"{base}{n}")
        return f"{base}{n}"

    def connect(cid: str, role: str, target: dict) -> None:
        out.connections.append(Connection(component_id=cid, pin_role=role, target=target))

    def power(cid: str) -> None:
        if "3V3" in rails:
            connect(cid, "VCC", {"kind": "rail", "rail": "3V3"})
        if "GND" in rails:
            connect(cid, "GND", {"kind": "rail", "rail": "GND"})

    lw = out.lorawan
    if lw.gps is not None and "uart_gps" not in present:
        bus_id = unique("gps_uart")
        out.buses.append(Bus(id=bus_id, type="uart", rx=lw.gps.rx_pin,
                             tx=lw.gps.tx_pin, baud_rate=lw.gps.baud))
        cid = unique(_GPS_ID)
        out.components.append(Component(id=cid, library_id="uart_gps", label="GPS"))
        power(cid)
        connect(cid, "TX", {"kind": "bus", "bus_id": bus_id})
        connect(cid, "RX", {"kind": "bus", "bus_id": bus_id})

    if lw.dht22 is not None and "dht" not in present:
        cid = unique(_DHT_ID)
        out.components.append(Component(id=cid, library_id="dht", label="DHT",
                                        params={"model": "DHT22"}))
        power(cid)
        connect(cid, "DATA", {"kind": "gpio", "pin": lw.dht22.pin})

    if lw.oled is not None and lw.oled.enabled and "ssd1306" not in present:
        bus_id = next((b.id for b in out.buses if b.type == "i2c"), None)
        if bus_id is None and i2c_default.get("sda") and i2c_default.get("scl"):
            bus_id = unique("i2c0")
            out.buses.append(Bus(id=bus_id, type="i2c",
                                 sda=i2c_default["sda"], scl=i2c_default["scl"]))
        ob = onboard.get("oled_ssd1306") or {}
        params: dict = {"address": ob.get("address", "0x3C")}
        if ob.get("vext"):
            params["vext_pin"] = ob["vext"]
        cid = unique(_OLED_ID)
        out.components.append(Component(id=cid, library_id="ssd1306", label="OLED", params=params))
        power(cid)
        if bus_id is not None:
            connect(cid, "SDA", {"kind": "bus", "bus_id": bus_id})
            connect(cid, "SCL", {"kind": "bus", "bus_id": bus_id})
        if ob.get("reset"):
            connect(cid, "RESET", {"kind": "gpio", "pin": ob["reset"]})

    lw.gps = lw.dht22 = lw.oled = None
    return out
