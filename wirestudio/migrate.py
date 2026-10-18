"""Bring a `design.json` document up to the current schema version.

A migration is a chain of steps, each from one `schema_version` to the
next, over the raw document. Every path that reads a design runs the
chain first: the design stores on load, the REST and MCP entry points on
input, and the generate CLI. `python -m wirestudio.migrate design.json`
runs it by hand and `--check` makes a gate of it.

Steps change only what they are about and leave the rest of the
document byte-for-byte as it was, so a migrated file diffs as the change
it carries and nothing else.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from wirestudio.library import Library

CURRENT_SCHEMA_VERSION = "0.3"


class MigrationError(ValueError):
    """The document cannot be brought to the current version."""


@dataclass(frozen=True)
class Step:
    from_version: str
    to_version: str
    name: str
    apply: "Callable[[dict, Library], dict]"


@dataclass
class Migration:
    document: dict
    from_version: str
    to_version: str
    applied: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.applied)


_UNREAD_TOP = ("created_at", "updated_at", "agent")
_UNREAD_LORAWAN = ("chirpstack_application_id", "device_profile_id", "provisioning", "dev_eui")


def _drop_unread_fields(raw: dict, library) -> dict:
    """0.2 -> 0.3: the fields the schema audit found nothing read or
    wrote. Timestamps no store maintained, the `agent` pointer (sessions
    live in their own store), and the LoRaWAN provisioning identifiers the
    provision endpoints take from the request and ChirpStack instead."""
    out = {k: v for k, v in raw.items() if k not in _UNREAD_TOP}
    lw = raw.get("lorawan")
    if isinstance(lw, dict) and any(k in lw for k in _UNREAD_LORAWAN):
        out["lorawan"] = {k: v for k, v in lw.items() if k not in _UNREAD_LORAWAN}
    return out


def _lower_lorawan_sugar(raw: dict, library) -> dict:
    """0.1 -> 0.2: `lorawan.gps` / `dht22` / `oled` become the `uart_gps`,
    `dht` and `ssd1306` components, buses and connections they stood for.
    A document without the blocks only changes its version."""
    from wirestudio.model import Design
    from wirestudio.targets.lorawan.lower import SUGAR_FIELDS, lower_lorawan_sugar

    lw = raw.get("lorawan") or {}
    if not any(lw.get(f) is not None for f in SUGAR_FIELDS):
        return raw
    # The model is the current one, so the fields 0.3 drops must not reach
    # it; they stay in the output until that step.
    before = Design.model_validate(_drop_unread_fields(raw, library))
    after = lower_lorawan_sugar(before, library)

    def new(items_before, items_after):
        return [
            item.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
            for item in items_after[len(items_before):]
        ]

    out = dict(raw)
    out["components"] = list(raw.get("components") or []) + [
        {**c, "params": c.get("params", {})} for c in new(before.components, after.components)
    ]
    out["buses"] = list(raw.get("buses") or []) + new(before.buses, after.buses)
    out["connections"] = list(raw.get("connections") or []) + new(before.connections, after.connections)
    out["lorawan"] = {k: v for k, v in lw.items() if k not in SUGAR_FIELDS}
    return out


STEPS: list[Step] = [
    Step("0.1", "0.2", "lower_lorawan_sugar", _lower_lorawan_sugar),
    Step("0.2", "0.3", "drop_unread_fields", _drop_unread_fields),
]


def needs_migration(raw: dict) -> bool:
    return raw.get("schema_version") != CURRENT_SCHEMA_VERSION


def migrate(raw: dict, library=None) -> Migration:
    """The document at the current schema version, with the steps it took.
    Raises `MigrationError` for a document with no version, one this
    wirestudio does not know, or one newer than it writes. `library` is
    resolved to the default library the first time a step needs it."""
    if not isinstance(raw, dict):
        raise MigrationError("a design is a JSON object")
    version = raw.get("schema_version")
    if not isinstance(version, str) or not version:
        raise MigrationError("design has no schema_version")
    result = Migration(document=raw, from_version=version, to_version=version)
    if version == CURRENT_SCHEMA_VERSION:
        return result
    known = {s.from_version for s in STEPS} | {CURRENT_SCHEMA_VERSION}
    if version not in known:
        raise MigrationError(
            f"schema_version {version!r} is not one this wirestudio can read "
            f"(it writes {CURRENT_SCHEMA_VERSION}); the design may come from a newer release"
        )
    document = raw
    while version != CURRENT_SCHEMA_VERSION:
        step = next(s for s in STEPS if s.from_version == version)
        if library is None:
            from wirestudio.library import default_library
            library = default_library()
        document = {**step.apply(document, library), "schema_version": step.to_version}
        result.applied.append(step.name)
        version = step.to_version
    result.document = document
    result.to_version = version
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wirestudio.migrate",
        description="Bring design.json files up to the current schema version.",
    )
    parser.add_argument("designs", nargs="+", type=Path, help="design.json files")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true",
                      help="rewrite each file in place (default: print the migrated document)")
    mode.add_argument("--check", action="store_true",
                      help="change nothing; exit 1 if any file is not at the current version")
    args = parser.parse_args(argv)

    stale = 0
    for path in args.designs:
        raw = json.loads(path.read_text())
        try:
            result = migrate(raw)
        except MigrationError as e:
            print(f"{path}: {e}", file=sys.stderr)
            return 2
        if args.check:
            if result.changed:
                stale += 1
                print(f"{path}: {result.from_version} -> {result.to_version} "
                      f"({', '.join(result.applied)})", file=sys.stderr)
            continue
        if args.write:
            if result.changed:
                path.write_text(json.dumps(result.document, indent=2) + "\n")
                print(f"{path}: {result.from_version} -> {result.to_version}", file=sys.stderr)
            continue
        json.dump(result.document, sys.stdout, indent=2)
        sys.stdout.write("\n")
    if args.check and stale:
        print(f"{stale} file(s) need `python -m wirestudio.migrate --write`", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
