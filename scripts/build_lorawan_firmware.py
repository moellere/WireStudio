"""Build the LoRaWAN firmware for every radio board -- the CI compile gate.

Mirrors scripts/check_examples.py for the esphome target: it exercises the C++
codegen + PlatformIO toolchain so an upstream RadioLib / LoRaWAN_ESP32 / toolchain
release that breaks the build is caught. Builds each board the lorawan target
offers, then designs that between them carry every library component with a
`lorawan:` block, so each block's C++ and libraries are compiled too. Board ids
passed as args build just those boards. Exit 0 = all built, 1 = a build failed,
2 = PlatformIO unavailable.

    python scripts/build_lorawan_firmware.py [board_id ...]
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wirestudio.library import default_library  # noqa: E402
from wirestudio.model import Design  # noqa: E402
from wirestudio.targets import get_target  # noqa: E402
from wirestudio.targets.lorawan.codec import fields_for  # noqa: E402
from wirestudio.targets.lorawan.compile import compile_firmware, platformio_status  # noqa: E402


def _design(board_id: str) -> Design:
    return Design(
        schema_version="0.1",
        id=f"ci-{board_id}",
        name=board_id,
        target="lorawan",
        lorawan={},
        board={"library_id": board_id, "mcu": "esp32"},
        power={"supply": "usb", "rail_voltage_v": 3.3},
    )


_COMPONENT_BOARD = "ttgo-lora32-v2"
_SIGNAL_KINDS = ("digital_in", "digital_out", "analog_in", "adc", "pwm", "spi_cs")
_SPI_KINDS = ("spi_clk", "spi_miso", "spi_mosi")
_UART_KINDS = ("uart_tx", "uart_rx")
_UARTS = 2  # the ESP32's UART1 and UART2; UART0 is the console


def _field_names(comp, inst: str) -> set[str]:
    return {f.name.replace("{{ id }}", inst) for f in comp.lorawan.fields}


def component_designs(lib) -> list[Design]:
    """Designs on one radio board that between them carry every component with
    a `lorawan:` block, split so no design repeats a payload field name or
    needs more UARTs than the board has. A part on a hub (a Modbus meter, an
    ADC channel) goes in with an instance of its hub. A component whose fields
    the board already reports (its battery divider, a PMIC) is left out: the
    board builds compile those blocks."""
    board_fields = {f["name"] for f in fields_for(_design(_COMPONENT_BOARD), lib)}
    groups: list[dict] = []
    for comp in sorted(lib.list_components(), key=lambda c: c.id):
        if comp.lorawan is None:
            continue
        hub = next((p.parent_library_id for p in comp.electrical.pins if p.kind == "hub_ref"), None)
        if hub is None and any(
            p.kind == "hub_ref" and p.parent_library_id == comp.id
            for c in lib.list_components() for p in c.electrical.pins
        ):
            continue  # a hub rides in with the parts on it
        inst = comp.id.replace("-", "_")
        names = _field_names(comp, inst)
        if names & board_fields:
            continue
        unit = [comp.id] if hub is None else [hub, comp.id]
        uarts = sum("uart" in lib.component(cid).lorawan.requires for cid in unit)
        for g in groups:
            new_uarts = uarts - (hub in g["members"] and "uart" in lib.component(hub).lorawan.requires)
            if not g["names"] & names and g["uarts"] + new_uarts <= _UARTS:
                g["names"] |= names
                g["uarts"] += new_uarts
                g["members"] += [cid for cid in unit if cid not in g["members"]]
                break
        else:
            groups.append({"names": set(names), "uarts": uarts, "members": list(unit)})
    board = lib.board(_COMPONENT_BOARD)
    spi = board.default_buses["spi"]
    designs = []
    for n, g in enumerate(groups):
        # Pins only have to exist for the build; two parts may share one.
        gpios = itertools.cycle(["GPIO36", "GPIO39", "GPIO34", "GPIO4", "GPIO25", "GPIO2", "GPIO15", "GPIO12"])
        uart_pins = iter([("GPIO16", "GPIO17"), ("GPIO32", "GPIO33")])
        components, connections = [], []
        buses = [{"id": "i2c0", "type": "i2c", "sda": "GPIO21", "scl": "GPIO22"},
                 {"id": "ow0", "type": "1wire", "pin": "GPIO13"},
                 {"id": "spi_bus0", "type": "spi", **spi}]
        insts = {cid: cid.replace("-", "_") for cid in g["members"]}
        for cid in g["members"]:
            inst = insts[cid]
            components.append({"id": inst, "library_id": cid, "label": cid, "params": {}})
            uart_bus = None
            for pin in lib.component(cid).electrical.pins:
                if pin.kind in ("i2c_sda", "i2c_scl"):
                    target = {"kind": "bus", "bus_id": "i2c0"}
                elif pin.kind == "onewire_data":
                    target = {"kind": "bus", "bus_id": "ow0"}
                elif pin.kind in _SPI_KINDS:
                    target = {"kind": "bus", "bus_id": "spi_bus0"}
                elif pin.kind in _UART_KINDS:
                    if uart_bus is None:
                        rx, tx = next(uart_pins)
                        uart_bus = f"uart_{inst}"
                        buses.append({"id": uart_bus, "type": "uart", "rx": rx, "tx": tx, "baud_rate": 9600})
                    target = {"kind": "bus", "bus_id": uart_bus}
                elif pin.kind == "hub_ref":
                    target = {"kind": "component", "component_id": insts[pin.parent_library_id]}
                elif pin.kind in _SIGNAL_KINDS:
                    target = {"kind": "gpio", "pin": next(gpios)}
                else:
                    continue
                connections.append({"component_id": inst, "pin_role": pin.role, "target": target})
        designs.append(Design.model_validate({
            "schema_version": "1.0", "id": f"ci-components-{n + 1}", "name": f"components {n + 1}",
            "target": "lorawan", "lorawan": {},
            "board": {"library_id": _COMPONENT_BOARD, "mcu": "esp32"},
            "power": {"supply": "usb", "rail_voltage_v": 3.3},
            "components": components,
            "buses": buses,
            "connections": connections,
        }))
    return designs


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    lib = default_library()
    boards = argv or get_target("lorawan").board_ids(lib)

    status = platformio_status()
    if not status["available"]:
        print(f"PlatformIO unavailable: {status['reason']}")
        return 2
    print(f"PlatformIO: {status['version']}")

    builds = [(board_id, _design(board_id)) for board_id in boards]
    if not argv:
        builds += [(f"{d.id} ({', '.join(c.library_id for c in d.components)})", d)
                   for d in component_designs(lib)]
    failures: list[str] = []
    for name, design in builds:
        print(f"\n=== building {name} ===", flush=True)
        # use_cache=False: CI must actually compile, not trust a warm cache.
        result = compile_firmware(design, lib, use_cache=False)
        if result.ok:
            print(f"OK {name} (env={result.env}) -> {result.bin_path}")
        else:
            print(result.log[-3000:])
            print(f"FAILED {name}")
            failures.append(name)

    if failures:
        print(f"\nfirmware build failed for: {', '.join(failures)}")
        return 1
    print(f"\nall {len(builds)} firmware images built")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
