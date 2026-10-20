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
_SIGNAL_KINDS = ("digital_in", "digital_out", "analog_in", "adc", "pwm")


def component_designs(lib) -> list[Design]:
    """Designs on one radio board that between them carry every component with
    a `lorawan:` block, split so no design repeats a payload field name. A
    component whose fields the board already reports (its battery divider, a
    PMIC) is left out: the board builds compile those blocks."""
    board_fields = {f["name"] for f in fields_for(_design(_COMPONENT_BOARD), lib)}
    groups: list[tuple[set[str], list[str]]] = []
    for comp in sorted(lib.list_components(), key=lambda c: c.id):
        if comp.lorawan is None:
            continue
        names = {f.name for f in comp.lorawan.fields}
        if names & board_fields:
            continue
        for used, members in groups:
            if not used & names:
                used |= names
                members.append(comp.id)
                break
        else:
            groups.append((set(names), [comp.id]))
    designs = []
    for n, (_, members) in enumerate(groups):
        # Pins only have to exist for the build; two parts may share one.
        gpios = itertools.cycle(["GPIO36", "GPIO39", "GPIO34", "GPIO4", "GPIO25", "GPIO2", "GPIO15", "GPIO12"])
        components, connections = [], []
        for cid in members:
            inst = cid.replace("-", "_")
            components.append({"id": inst, "library_id": cid, "label": cid, "params": {}})
            for pin in lib.component(cid).electrical.pins:
                if pin.kind in ("i2c_sda", "i2c_scl"):
                    target = {"kind": "bus", "bus_id": "i2c0"}
                elif pin.kind == "onewire_data":
                    target = {"kind": "bus", "bus_id": "ow0"}
                elif pin.kind in _SIGNAL_KINDS:
                    target = {"kind": "gpio", "pin": next(gpios)}
                else:
                    continue
                connections.append({"component_id": inst, "pin_role": pin.role, "target": target})
        designs.append(Design.model_validate({
            "schema_version": "0.3", "id": f"ci-components-{n + 1}", "name": f"components {n + 1}",
            "target": "lorawan", "lorawan": {},
            "board": {"library_id": _COMPONENT_BOARD, "mcu": "esp32"},
            "power": {"supply": "usb", "rail_voltage_v": 3.3},
            "components": components,
            "buses": [{"id": "i2c0", "type": "i2c", "sda": "GPIO21", "scl": "GPIO22"},
                      {"id": "ow0", "type": "1wire", "pin": "GPIO13"}],
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
