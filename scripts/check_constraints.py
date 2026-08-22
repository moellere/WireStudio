#!/usr/bin/env python3
"""Assert constraints.txt still pins everything the image installs.

`constraints.txt` caps the versions the runtime image resolves. It only
stays true while it names every package pip pulls in -- a dependency
added to pyproject.toml is *not* pinned, nothing fails, and the file
quietly stops being complete. That is the drift the file exists to
prevent, so it would go unnoticed for as long as it did last time.

The check is one-directional: every **installed** package must be
pinned. The reverse is not required and would be wrong -- the file is
generated from the `-full` image, so it carries pins for platformio and
the lorawan/pcb extras that a base install never touches. A constraint
on a package pip is not installing is inert.

Run against an environment built *with* the constraints applied:

    pip install -c constraints.txt .
    python scripts/check_constraints.py

Use the image's Python (3.11). A freeze from a newer interpreter can
name wheels that do not exist for 3.11, and the resolved set can differ.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# pip normalises distribution names for comparison: case-insensitive,
# with runs of -_. collapsed to a single dash (PEP 503).
_NORMALISE = re.compile(r"[-_.]+")

# Always present in a venv, never a project dependency, and not worth
# pinning -- pip upgrades itself and setuptools ships with the venv.
IGNORE = {"pip", "setuptools", "wheel", "wirestudio"}


def normalise(name: str) -> str:
    return _NORMALISE.sub("-", name).lower()


def pinned_names(path: Path) -> set[str]:
    names = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        names.add(normalise(line.split("==", 1)[0]))
    return names


def installed_names() -> set[str]:
    out = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--exclude-editable"],
        capture_output=True, text=True, check=True,
    ).stdout
    names = set()
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("-") or " @ " in line:
            continue
        if "==" not in line:
            continue
        names.add(normalise(line.split("==", 1)[0]))
    return names


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--constraints", type=Path,
                    default=REPO_ROOT / "constraints.txt")
    args = ap.parse_args()

    pinned = pinned_names(args.constraints)
    installed = installed_names() - IGNORE
    unpinned = sorted(installed - pinned)

    print(f"python      : {sys.version.split()[0]}")
    print(f"pinned      : {len(pinned)}")
    print(f"installed   : {len(installed)}")
    print(f"unpinned    : {len(unpinned)}")

    if not unpinned:
        print("\nOK: every installed package is pinned.")
        return 0

    # Flush first: the summary above is on stdout and the failure below on
    # stderr, and unflushed stdout lands after it in a CI log.
    sys.stdout.flush()
    print("\nInstalled but not pinned in constraints.txt:", file=sys.stderr)
    for name in unpinned:
        print(f"  {name}", file=sys.stderr)
    print(
        "\nA dependency reached the image without a pin, so builds can "
        "drift again.\nRefresh constraints.txt -- see 'Refreshing the image "
        "constraints' in CONTRIBUTING.md.\nGenerate it against Python 3.11, "
        "the image's interpreter.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
