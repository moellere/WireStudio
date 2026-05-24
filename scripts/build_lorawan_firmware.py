"""Build the LoRaWAN firmware for every radio board -- the CI compile gate.

Mirrors scripts/check_examples.py for the esphome target: it exercises the C++
codegen + PlatformIO toolchain so an upstream RadioLib / LoRaWAN_ESP32 / toolchain
release that breaks the build is caught. Builds each board the lorawan target
offers (or the board ids passed as args). Exit 0 = all built, 1 = a build failed,
2 = PlatformIO unavailable.

    python scripts/build_lorawan_firmware.py [board_id ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wirestudio.library import default_library  # noqa: E402
from wirestudio.model import Design  # noqa: E402
from wirestudio.targets import get_target  # noqa: E402
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


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    lib = default_library()
    boards = argv or get_target("lorawan").board_ids(lib)

    status = platformio_status()
    if not status["available"]:
        print(f"PlatformIO unavailable: {status['reason']}")
        return 2
    print(f"PlatformIO: {status['version']}")

    failures: list[str] = []
    for board_id in boards:
        print(f"\n=== building {board_id} ===", flush=True)
        # use_cache=False: CI must actually compile, not trust a warm cache.
        result = compile_firmware(_design(board_id), lib, use_cache=False)
        if result.ok:
            print(f"OK {board_id} (env={result.env}) -> {result.bin_path}")
        else:
            print(result.log[-3000:])
            print(f"FAILED {board_id}")
            failures.append(board_id)

    if failures:
        print(f"\nfirmware build failed for: {', '.join(failures)}")
        return 1
    print(f"\nall {len(boards)} firmware images built")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
