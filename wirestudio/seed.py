"""Seed a design with a board's built-in (onboard) peripherals.

When a user adopts a dev board -- via USB detection or a fresh design --
the parts soldered onto it (LCD, button, IMU, ...) should already be on
the canvas. This reads the board's `onboard_peripherals` metadata and
emits the matching library components plus their wiring (rails, buses,
GPIO pins).

Peripherals the library has no component for yet (ir_tx, axp192, i2s
mic, ...) are skipped with an info warning so nothing silently
disappears. The mapping covers every onboard peripheral with a library
component across the bundled boards: addressable + plain LEDs, buttons,
ST7789 + SSD1306 displays, the MPU6886 IMU, the SX1276 LoRa radio, a
NEO-6M GPS, and a battery ADC.
"""
from __future__ import annotations

from typing import Callable, Optional

from wirestudio.library import Library, LibraryBoard

# A handler turns one onboard-peripheral entry (its key + params) into a
# component dict plus its connection dicts. It calls `ensure_bus(type)`
# to lazily materialise the board's default bus of that type, or
# `register_bus(...)` for a bespoke bus (e.g. a GPS UART), and returns
# None to skip (the board lacks a needed bus/pins).
Handler = Callable[[str, dict, "_SeedContext"], Optional[tuple[dict, list[dict]]]]


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

    def register_bus(self, bus_id: str, entry: dict) -> str:
        self.buses.setdefault(bus_id, entry)
        return bus_id


def _rail(component_id: str, role: str, rail: str) -> dict:
    return {"component_id": component_id, "pin_role": role, "target": {"kind": "rail", "rail": rail}}


def _gpio(component_id: str, role: str, pin: str) -> dict:
    return {"component_id": component_id, "pin_role": role, "target": {"kind": "gpio", "pin": pin}}


def _bus(component_id: str, role: str, bus_id: str) -> dict:
    return {"component_id": component_id, "pin_role": role, "target": {"kind": "bus", "bus_id": bus_id}}


def _seed_button(key: str, params: dict, ctx: _SeedContext) -> Optional[tuple[dict, list[dict]]]:
    pin = params.get("pin")
    if not pin:
        return None
    comp: dict = {"id": "onboard_button", "library_id": "gpio_input", "label": "Onboard button", "params": {}}
    if params.get("inverted"):
        comp["params"]["filters"] = [{"invert": None}]
    return comp, [_gpio("onboard_button", "IN", pin)]


def _seed_led_plain(key: str, params: dict, ctx: _SeedContext) -> Optional[tuple[dict, list[dict]]]:
    pin = params.get("pin")
    if not pin:
        return None
    comp = {"id": "onboard_led", "library_id": "gpio_output", "label": "Onboard LED", "params": {}}
    return comp, [_gpio("onboard_led", "OUT", pin)]


def _seed_led_addressable(key: str, params: dict, ctx: _SeedContext) -> Optional[tuple[dict, list[dict]]]:
    pin = params.get("pin")
    if not pin:
        return None
    chipset = "SK6812" if "sk6812" in key else "WS2812"
    comp = {
        "id": "onboard_led", "library_id": "esp32_rmt_led_strip", "label": "Onboard RGB LED",
        "params": {"num_leds": params.get("count", 1), "chipset": chipset},
    }
    conns = [_rail("onboard_led", "VCC", "5V"), _rail("onboard_led", "GND", "GND"),
             _gpio("onboard_led", "DIN", pin)]
    return comp, conns


def _seed_ssd1306(key: str, params: dict, ctx: _SeedContext) -> Optional[tuple[dict, list[dict]]]:
    i2c = ctx.ensure_bus("i2c")
    if i2c is None:
        return None
    comp = {
        "id": "onboard_oled", "library_id": "ssd1306", "label": "Onboard OLED", "role": "display",
        "params": {"address": params.get("address", "0x3C"), "model": "SSD1306 128x64"},
    }
    conns = [_rail("onboard_oled", "VCC", "3V3"), _rail("onboard_oled", "GND", "GND"),
             _bus("onboard_oled", "SDA", i2c), _bus("onboard_oled", "SCL", i2c)]
    if params.get("reset"):
        conns.append(_gpio("onboard_oled", "RESET", params["reset"]))
    return comp, conns


def _seed_sx127x(key: str, params: dict, ctx: _SeedContext) -> Optional[tuple[dict, list[dict]]]:
    spi = ctx.ensure_bus("spi")
    if spi is None:
        return None
    comp = {
        "id": "onboard_lora", "library_id": "sx127x", "label": "Onboard LoRa radio",
        # LORA modulation requires preamble_size >= 6 in ESPHome.
        "params": {"frequency": params.get("frequency", 433000000), "modulation": "LORA",
                   "preamble_size": 8},
    }
    conns = [_rail("onboard_lora", "VCC", "3V3"), _rail("onboard_lora", "GND", "GND"),
             _bus("onboard_lora", "SCK", spi), _bus("onboard_lora", "MISO", spi),
             _bus("onboard_lora", "MOSI", spi)]
    for role, pkey in (("CS", "cs"), ("RST", "rst"), ("DIO0", "dio0")):
        if params.get(pkey):
            conns.append(_gpio("onboard_lora", role, params[pkey]))
    return comp, conns


def _seed_gps(key: str, params: dict, ctx: _SeedContext) -> Optional[tuple[dict, list[dict]]]:
    # Peripheral tx/rx are GPS-side labels. The MCU's tx must drive the
    # GPS RX (output-capable pin), and the MCU's rx reads the GPS TX --
    # so the bus pins cross over. (On ESP32 the GPS TX often lands on an
    # input-only pin, which is fine for rx but illegal for tx.)
    gps_tx, gps_rx = params.get("tx"), params.get("rx")
    if not (gps_tx and gps_rx):
        return None
    # 'uart0/1/2' are reserved ESPHome ids (the hardware UART peripherals).
    bus_id = ctx.register_bus("gps_uart", {
        "id": "gps_uart", "type": "uart", "tx": gps_rx, "rx": gps_tx,
        "baud_rate": params.get("baud", 9600),
    })
    comp = {
        "id": "onboard_gps", "library_id": "uart_gps", "label": "Onboard GPS",
        "params": {"sensors": {
            "latitude": {"name": "GPS Latitude"},
            "longitude": {"name": "GPS Longitude"},
            "altitude": {"name": "GPS Altitude"},
            "satellites": {"name": "GPS Satellites"},
        }},
    }
    conns = [_rail("onboard_gps", "VCC", "3V3"), _rail("onboard_gps", "GND", "GND"),
             _bus("onboard_gps", "TX", bus_id), _bus("onboard_gps", "RX", bus_id)]
    return comp, conns


def _seed_battery_adc(key: str, params: dict, ctx: _SeedContext) -> Optional[tuple[dict, list[dict]]]:
    pin = params.get("pin")
    if not pin:
        return None
    p: dict = {"attenuation": "11db", "unit_of_measurement": "V"}
    if params.get("divider"):
        p["filters"] = [{"multiply": params["divider"]}]
    comp = {"id": "onboard_battery", "library_id": "adc", "label": "Battery voltage", "params": p}
    return comp, [_gpio("onboard_battery", "IN", pin)]


def _seed_st7789(key: str, params: dict, ctx: _SeedContext) -> Optional[tuple[dict, list[dict]]]:
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
    for role, pkey in (("CS", "cs"), ("DC", "dc"), ("RESET", "reset"), ("BACKLIGHT", "backlight")):
        if params.get(pkey):
            conns.append(_gpio("onboard_display", role, params[pkey]))
    return comp, conns


def _seed_mpu6886(key: str, params: dict, ctx: _SeedContext) -> Optional[tuple[dict, list[dict]]]:
    # Honour the IMU's own I2C pins when the board gives them (the Atom
    # Matrix puts the IMU on a separate bus from the Grove port); else
    # fall back to the board's default I2C bus.
    if params.get("sda") and params.get("scl"):
        i2c = ctx.register_bus("i2c_imu", {
            "id": "i2c_imu", "type": "i2c", "sda": params["sda"], "scl": params["scl"],
        })
    else:
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
    if key == "led":
        return _seed_led_plain
    if key.startswith("led_"):
        return _seed_led_addressable
    if key.startswith("display_st7789"):
        return _seed_st7789
    if key.startswith("oled_ssd1306"):
        return _seed_ssd1306
    if key.startswith("imu_mpu6886"):
        return _seed_mpu6886
    if key.startswith("lora_sx1276"):
        return _seed_sx127x
    if key.startswith("gps_neo6m"):
        return _seed_gps
    if key == "battery_adc":
        return _seed_battery_adc
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
            result = handler(key, params or {}, ctx)
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
