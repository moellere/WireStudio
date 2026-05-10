"""Default-target picking + bus seeding for newly-added components.

Mirror of the frontend `web/src/lib/design.ts` helpers (`addComponent`,
`prepareBusesForLib`, `defaultTargetForPin`). Kept in sync by hand: when
the frontend changes one, change the matching helper here, otherwise the
MCP tool surface and the web UI drift in their interpretation of the
same design edit.

The helpers are deliberately pure -- they take dicts in and return new
dicts -- so they're easy to test and easy to call from any code path
that mutates a design (today: the MCP `add_component` tool).
"""
from __future__ import annotations

from typing import Any, Optional

from wirestudio.library import Library, LibraryBoard, LibraryComponent


_BUS_KIND_TO_TYPE: dict[str, str] = {
    "i2c_sda": "i2c", "i2c_scl": "i2c",
    "spi_clk": "spi", "spi_miso": "spi", "spi_mosi": "spi",
    "i2s_lrclk": "i2s", "i2s_bclk": "i2s",
    "uart_rx": "uart", "uart_tx": "uart",
    "onewire_data": "1wire",
}


def needed_bus_types(lib: LibraryComponent) -> set[str]:
    """Bus types this component needs based on its pin kinds."""
    return {
        _BUS_KIND_TO_TYPE[p.kind] for p in lib.electrical.pins
        if p.kind in _BUS_KIND_TO_TYPE
    }


def default_target_for_pin(
    pin_kind: str,
    *,
    rails: list[dict],
    buses: list[dict],
    vcc_min: Optional[float] = None,
    vcc_max: Optional[float] = None,
) -> dict:
    """Pick the most plausible target for a fresh connection.

    Power pins → lowest rail satisfying the part's [vcc_min, vcc_max]
    band, falling back to 3V3 then any non-zero rail. Ground → 0V rail
    or one literally named GND. Bus pins → first bus of the matching
    type, or an empty placeholder bus_id (the form will surface as
    "(invalid)" so the user can pick or fix). Everything else → empty
    GPIO pin (solve_pins fills these in).
    """
    if pin_kind == "power":
        candidates = [
            r for r in rails
            if (vcc_min is None or r["voltage"] >= vcc_min)
            and (vcc_max is None or r["voltage"] <= vcc_max)
        ]
        candidates.sort(key=lambda r: r["voltage"])
        chosen = (
            (candidates[0] if candidates else None)
            or next((r for r in rails if r["name"] == "3V3"), None)
            or next((r for r in rails if r["voltage"] > 0), None)
            or (rails[0] if rails else None)
        )
        return {"kind": "rail", "rail": chosen["name"] if chosen else "3V3"}

    if pin_kind == "ground":
        gnd = (
            next((r["name"] for r in rails if r["voltage"] == 0), None)
            or next((r["name"] for r in rails if "gnd" in r["name"].lower()), None)
            or "GND"
        )
        return {"kind": "rail", "rail": gnd}

    bus_type = _BUS_KIND_TO_TYPE.get(pin_kind)
    if bus_type:
        match = next((b for b in buses if b.get("type") == bus_type), None)
        return {"kind": "bus", "bus_id": match["id"] if match else ""}

    # spi_cs, i2s_dout, digital_in/out, analog_in -> per-component native GPIO.
    return {"kind": "gpio", "pin": ""}


def prepare_buses(design: dict, lib: LibraryComponent, board: LibraryBoard) -> dict:
    """Append any bus types the component needs but the design lacks.

    Pulls SDA/SCL/etc. from the board's `default_buses` block when
    available; falls back to an empty bus skeleton (the user fills in
    via the inspector when that lands). Mutates the design dict in
    place and returns it.
    """
    buses = design.setdefault("buses", [])
    have_types = {b.get("type") for b in buses}
    need = needed_bus_types(lib) - have_types
    if not need:
        return design

    # Library board exposes `default_buses` -- a dict of bus type -> default
    # field map (e.g. {"i2c": {"sda": "GPIO21", "scl": "GPIO22"}}).
    defaults: dict[str, dict[str, Any]] = getattr(board, "default_buses", {}) or {}

    for bus_type in need:
        bus: dict[str, Any] = {"id": _next_bus_id(buses, bus_type), "type": bus_type}
        bus.update(defaults.get(bus_type, {}))
        buses.append(bus)
    return design


def _next_bus_id(existing: list[dict], bus_type: str) -> str:
    used = {b.get("id") for b in existing}
    for n in range(1, 1000):
        candidate = f"{bus_type}_{n}"
        if candidate not in used:
            return candidate
    return f"{bus_type}_{len(existing)}"


def seed_connections(
    design: dict,
    instance_id: str,
    lib: LibraryComponent,
    board: Optional[LibraryBoard],
) -> dict:
    """Append a connection per pin in the library entry for the new instance.

    Mirrors the frontend `addComponent`: every pin role gets a connection
    targeted at the most-plausible destination (rail / bus / empty GPIO).
    Empty GPIO targets are placeholders that `solve_pins` will fill in.
    """
    rails = (
        [{"name": r.name, "voltage": r.voltage} for r in board.rails]
        if board is not None else []
    )
    buses = list(design.get("buses") or [])
    connections = design.setdefault("connections", [])

    for pin in lib.electrical.pins:
        target = default_target_for_pin(
            pin.kind,
            rails=rails,
            buses=buses,
            vcc_min=lib.electrical.vcc_min,
            vcc_max=lib.electrical.vcc_max,
        )
        connections.append({
            "component_id": instance_id,
            "pin_role": pin.role,
            "target": target,
        })
    return design


def add_component_with_connections(
    design: dict,
    library: Library,
    *,
    library_id: str,
    label: Optional[str] = None,
    instance_id_hint: Optional[str] = None,
    params: Optional[dict] = None,
) -> tuple[str, dict]:
    """Add a component instance + auto-seed its buses and connections.

    Returns (instance_id, design). The design is mutated in place.
    Raises FileNotFoundError if `library_id` isn't in the library.
    """
    lib = library.component(library_id)
    components = design.setdefault("components", [])
    used = {c["id"] for c in components}

    if instance_id_hint and instance_id_hint not in used:
        instance_id = instance_id_hint
    else:
        base = "".join(ch if ch.isalnum() else "_" for ch in library_id)
        n = 1
        while f"{base}_{n}" in used:
            n += 1
        instance_id = f"{base}_{n}"

    components.append({
        "id": instance_id,
        "library_id": library_id,
        "label": label or lib.name,
        "params": params or {},
    })

    board: Optional[LibraryBoard] = None
    board_id = (design.get("board") or {}).get("library_id")
    if board_id:
        try:
            board = library.board(board_id)
        except FileNotFoundError:
            board = None

    if board is not None:
        prepare_buses(design, lib, board)
    seed_connections(design, instance_id, lib, board)
    return instance_id, design
