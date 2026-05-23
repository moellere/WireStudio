"""Seed a design with a board's built-in (onboard) peripherals.

When a user adopts a dev board -- via USB detection or a fresh design --
the parts soldered onto it (LCD, button, IMU, ...) should already be on
the canvas. This reads the board's `onboard_peripherals` metadata and
emits the matching library components plus their wiring (rails, buses,
GPIO pins).

Peripherals the library has no component for yet (ir_tx, axp192, i2s
mic, ...) are skipped with an info warning so nothing silently
disappears. The mapping currently covers the M5Stack AtomS3 set
(display, button, IMU); other boards' peripherals fall through to the
skip-with-warning path until their handlers land.
"""
from __future__ import annotations

from typing import Callable, Optional

from wirestudio.library import Library, LibraryBoard

# A handler turns one onboard-peripheral entry into a component dict plus
# its connection dicts. It calls `ensure_bus(type)` to lazily materialise
# the board's default bus of that type and returns its id (or None if the
# board declares no such bus).
Handler = Callable[[dict, "_SeedContext"], Optional[tuple[dict, list[dict]]]]


class _SeedContext:
    def __init__(self, board: LibraryBoard):
        self.board = board
        self.buses: dict[str, dict] = {}

    def ensure_bus(self, bus_type: str) -> Optional[str]:
        bus_id = f"{bus_type}0"
        if bus_id in self.buses:
            return bus_id
        spec = (self.board.default_buses or {}).get(bus_type)
        if not spec:
            return None
        self.buses[bus_id] = {"id": bus_id, "type": bus_type, **spec}
        return bus_id


def _rail(component_id: str, role: str, rail: str) -> dict:
    return {"component_id": component_id, "pin_role": role, "target": {"kind": "rail", "rail": rail}}


def _gpio(component_id: str, role: str, pin: str) -> dict:
    return {"component_id": component_id, "pin_role": role, "target": {"kind": "gpio", "pin": pin}}


def _bus(component_id: str, role: str, bus_id: str) -> dict:
    return {"component_id": component_id, "pin_role": role, "target": {"kind": "bus", "bus_id": bus_id}}


def _seed_button(params: dict, ctx: _SeedContext) -> Optional[tuple[dict, list[dict]]]:
    pin = params.get("pin")
    if not pin:
        return None
    comp: dict = {"id": "onboard_button", "library_id": "gpio_input", "label": "Onboard button", "params": {}}
    if params.get("inverted"):
        comp["params"]["filters"] = [{"invert": None}]
    return comp, [_gpio("onboard_button", "IN", pin)]


def _seed_st7789(params: dict, ctx: _SeedContext) -> Optional[tuple[dict, list[dict]]]:
    spi = ctx.ensure_bus("spi")
    if spi is None:
        return None
    comp = {
        "id": "onboard_display", "library_id": "st7789", "label": "Onboard display", "role": "display",
        "params": {
            "model": "Custom",
            "width": params.get("width", 240),
            "height": params.get("height", 320),
            # ESPHome's Custom st7789v requires all four geometry params.
            "offset_width": params.get("offset_width", 0),
            "offset_height": params.get("offset_height", 0),
        },
    }
    conns = [
        _rail("onboard_display", "VCC", "3V3"),
        _rail("onboard_display", "GND", "GND"),
        _bus("onboard_display", "SCK", spi),
        _bus("onboard_display", "MOSI", spi),
    ]
    for role, key in (("CS", "cs"), ("DC", "dc"), ("RESET", "reset"), ("BACKLIGHT", "backlight")):
        if params.get(key):
            conns.append(_gpio("onboard_display", role, params[key]))
    return comp, conns


def _seed_mpu6886(params: dict, ctx: _SeedContext) -> Optional[tuple[dict, list[dict]]]:
    i2c = ctx.ensure_bus("i2c")
    if i2c is None:
        return None
    comp = {
        "id": "onboard_imu", "library_id": "mpu6886", "label": "Onboard IMU",
        "params": {"address": params.get("address", "0x68")},
    }
    conns = [
        _rail("onboard_imu", "VCC", "3V3"),
        _rail("onboard_imu", "GND", "GND"),
        _bus("onboard_imu", "SDA", i2c),
        _bus("onboard_imu", "SCL", i2c),
    ]
    return comp, conns


def _component_exists(library: Library, library_id: str) -> bool:
    try:
        library.component(library_id)
        return True
    except FileNotFoundError:
        return False


def _handler_for(key: str) -> Optional[Handler]:
    if key in ("button", "boot_button"):
        return _seed_button
    if key.startswith("display_st7789"):
        return _seed_st7789
    if key.startswith("imu_mpu6886"):
        return _seed_mpu6886
    return None


def seed_onboard_components(board: LibraryBoard, library: Library) -> dict:
    """Return design fragments for `board`'s onboard peripherals.

    Shape: ``{"components": [...], "buses": [...], "connections": [...],
    "warnings": [...]}``. Unmapped peripherals (or ones whose target
    component is missing from the library) add an `onboard_unmapped`
    info warning rather than failing.
    """
    ctx = _SeedContext(board)
    components: list[dict] = []
    connections: list[dict] = []
    warnings: list[dict] = []

    for key, params in (board.onboard_peripherals or {}).items():
        handler = _handler_for(key)
        skip_reason: Optional[str] = None
        if handler is None:
            skip_reason = "no library component for it yet"
        else:
            result = handler(params or {}, ctx)
            if result is None:
                skip_reason = "the board lacks the bus/pins it needs"
            else:
                comp, conns = result
                if not _component_exists(library, comp["library_id"]):
                    skip_reason = f"library component '{comp['library_id']}' is missing"
                else:
                    components.append(comp)
                    connections.extend(conns)
        if skip_reason:
            warnings.append({
                "level": "info",
                "code": "onboard_unmapped",
                "text": f"Onboard '{key}' was not auto-added ({skip_reason}). Add it from the inspector if you need it.",
            })

    return {
        "components": components,
        "buses": list(ctx.buses.values()),
        "connections": connections,
        "warnings": warnings,
    }
