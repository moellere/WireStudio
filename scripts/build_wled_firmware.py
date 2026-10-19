"""Build WLED with an example's usermods compiled in -- the CI compile gate.

Mirrors scripts/build_lorawan_firmware.py: a shallow clone of the pinned
release, the example's platformio_override.ini, `pio run -e wirestudio`.
An upstream move (a usermod renamed, a library pin gone, the release's
environments reshaped) that breaks the build is caught here. Builds the
examples given, or the bundled usermod example. Exit 0 = built, 1 = a
build failed, 2 = the toolchain is missing.

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


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    lib = default_library()
    probe = status()
    if not probe["available"]:
        print(f"toolchain unavailable: {probe['reason']}")
        return 2
    print(f"PlatformIO {probe['version']}; WLED {probe['release']}")

    failures: list[str] = []
    for stem in argv or DEFAULT:
        design = Design.model_validate(json.loads((EXAMPLES / f"{stem}.json").read_text()))
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
