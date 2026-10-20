"""Build WLED with an example's usermods compiled in -- the CI compile gate.

Mirrors scripts/build_lorawan_firmware.py: a shallow clone of the pinned
release, the example's platformio_override.ini, `pio run -e wirestudio`.
An upstream move (a usermod renamed, a library pin gone, the release's
environments reshaped) that breaks the build is caught here. Builds the
examples given, or the bundled usermod example and designs that between
them carry every library component with a usermod block. Exit 0 =
built, 1 = a build failed, 2 = the toolchain is missing.

    python scripts/build_wled_firmware.py [example-stem ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wirestudio.library import default_library  # noqa: E402
from wirestudio.model import Design  # noqa: E402
from wirestudio.targets.wled_build import compile_firmware_events, status  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "wirestudio" / "examples"
DEFAULT = ["wled-sensor-strip"]


_SIGNAL_KINDS = ("digital_in", "digital_out", "analog_in", "adc", "pwm")


def usermod_designs(lib) -> list[Design]:
    """Designs on an ESP32 DevKitC that between them carry every component
    with a usermod block, split so no design enables a usermod twice."""
    groups: list[tuple[set[str], list[str]]] = []
    for comp in sorted(lib.list_components(), key=lambda c: c.id):
        if comp.wled is None or comp.wled.kind != "usermod":
            continue
        for defines, members in groups:
            if comp.wled.define not in defines:
                defines.add(comp.wled.define)
                members.append(comp.id)
                break
        else:
            groups.append(({comp.wled.define}, [comp.id]))
    designs = []
    for n, (_, members) in enumerate(groups):
        gpios = iter(["GPIO4", "GPIO13", "GPIO14", "GPIO25", "GPIO26", "GPIO27", "GPIO32", "GPIO33"])
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
            "schema_version": "0.3", "id": f"ci-usermods-{n + 1}", "name": f"usermods {n + 1}",
            "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32"},
            "power": {"supply": "usb", "rail_voltage_v": 3.3},
            "components": components,
            "buses": [{"id": "i2c0", "type": "i2c", "sda": "GPIO21", "scl": "GPIO22"},
                      {"id": "ow0", "type": "1wire", "pin": "GPIO23"}],
            "connections": connections,
        }))
    return designs


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    lib = default_library()
    probe = status()
    if not probe["available"]:
        print(f"toolchain unavailable: {probe['reason']}")
        return 2
    print(f"PlatformIO {probe['version']}; WLED {probe['release']}")

    builds = [(stem, Design.model_validate(json.loads((EXAMPLES / f"{stem}.json").read_text())))
              for stem in argv or DEFAULT]
    if not argv:
        builds += [(f"{d.id} ({', '.join(c.library_id for c in d.components)})", d)
                   for d in usermod_designs(lib)]
    failures: list[str] = []
    for stem, design in builds:
        print(f"\n=== building {stem} ===", flush=True)
        done: dict = {}
        tail: list[str] = []
        # use_cache=False: CI must compile, not trust a warm cache.
        for event in compile_firmware_events(design, lib, use_cache=False):
            if event["type"] == "log":
                tail = (tail + [event["data"]])[-60:]
            else:
                done = event
        if done.get("ok"):
            print(f"OK {stem} -> {done['bin']}" + (f" (factory: {done['factory']})" if done.get("factory") else ""))
        else:
            print("".join(tail))
            print(f"FAILED {stem}")
            failures.append(stem)
    if failures:
        print(f"\nWLED build failed for: {', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
