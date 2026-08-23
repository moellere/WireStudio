#!/usr/bin/env python3
"""Fail when the [Unreleased] section has duplicate or unknown headings.

Every PR adds its own entry, so `[Unreleased]` accumulates whatever
headings each author reached for. Four PRs each writing `### Fixed`
leaves four separate Fixed blocks, and the duplication is only visible
when someone reads the whole section at release time -- which is exactly
when nobody wants to be reorganising a changelog. 0.27.0 and 0.28.2 both
needed that tidy-up.

A misspelled heading (`### Fixes`) fails the same way and is harder to
spot: the entry is present, looks right in the diff, and silently forms
its own group.

Only `[Unreleased]` is checked. Released sections are history -- failing
CI on a past release's layout would block unrelated work to fix
something nobody is reading.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Keep a Changelog's set, which is what this file has always used.
VALID = ["Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"]

_RELEASE = re.compile(r"^## ", re.M)
_HEADING = re.compile(r"^### +(.+?)\s*$", re.M)


def unreleased_section(text: str) -> str | None:
    """The [Unreleased] body, up to the next `## ` heading."""
    start = text.find("## [Unreleased]")
    if start == -1:
        return None
    rest = text[start + len("## [Unreleased]"):]
    nxt = _RELEASE.search(rest)
    return rest[: nxt.start()] if nxt else rest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--changelog", type=Path, default=REPO_ROOT / "CHANGELOG.md")
    args = ap.parse_args()

    text = args.changelog.read_text()
    section = unreleased_section(text)
    if section is None:
        print("::error::CHANGELOG.md has no '## [Unreleased]' section.", file=sys.stderr)
        return 1

    headings = _HEADING.findall(section)
    counts = Counter(headings)
    dupes = sorted(h for h, n in counts.items() if n > 1)
    unknown = sorted({h for h in headings if h not in VALID})

    print(f"[Unreleased] headings: {headings or '(none)'}")

    if not dupes and not unknown:
        print("OK: no duplicate or unknown headings.")
        return 0

    sys.stdout.flush()
    if dupes:
        print("::error::Duplicate headings under [Unreleased]:", file=sys.stderr)
        for h in dupes:
            print(f"  '### {h}' appears {counts[h]} times", file=sys.stderr)
        print(
            "\nMerge the entries under a single heading. Separate blocks read as\n"
            "separate concerns and have to be reorganised by hand at release time.",
            file=sys.stderr,
        )
    if unknown:
        print("::error::Unknown headings under [Unreleased]:", file=sys.stderr)
        for h in unknown:
            print(f"  '### {h}'", file=sys.stderr)
        print(f"\nUse one of: {', '.join(VALID)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
