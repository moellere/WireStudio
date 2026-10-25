"""Bring a `design.json` document up to the current schema version.

A migration is a chain of steps, each from one `schema_version` to the
next, over the raw document. Every path that reads a design runs the
chain first: the design stores on load, the REST and MCP entry points on
input, and the generate CLI. `python -m wirestudio.migrate design.json`
runs it by hand and `--check` makes a gate of it.

Steps change only what they are about and leave the rest of the
document byte-for-byte as it was, so a migrated file diffs as the change
it carries and nothing else.

Repairs run after the steps on every document, at any version: fixes for
a document no version of the studio should have written but some did.
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
    from wirestudio.model import Design

CURRENT_SCHEMA_VERSION = "1.0"


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


_SUGAR_FIELDS = ("gps", "dht22", "oled")

# Instance ids match what the codec used to synthesize, so device-profile
# names and the C++ singletons a lowered design produces are the ones a
# device provisioned from the same design already carries.
_GPS_ID, _DHT_ID, _OLED_ID = "gps", "dht1", "oled"


def _lower_lorawan_sugar(raw: dict, library) -> dict:
    """`lorawan.gps` / `dht22` / `oled` become the `uart_gps`, `dht` and
    `ssd1306` components, buses and connections they stood for, wired the
    way a user would have wired them. A block whose component the design
    already carries (by library id) is dropped rather than doubled. A
    document without the blocks is returned as is."""
    from wirestudio.model import Bus, Component, Connection

    lw = raw.get("lorawan")
    if not isinstance(lw, dict) or not any(lw.get(f) is not None for f in _SUGAR_FIELDS):
        return raw
    try:
        board = library.board((raw.get("board") or {}).get("library_id"))
    except FileNotFoundError:
        board = None
    rails = {r.name for r in board.rails} if board else set()
    onboard = (board.onboard_peripherals or {}) if board else {}
    i2c_default = (board.default_buses or {}).get("i2c", {}) if board else {}

    components = list(raw.get("components") or [])
    buses = list(raw.get("buses") or [])
    connections = list(raw.get("connections") or [])
    present = {c.get("library_id") for c in components}
    ids = {c.get("id") for c in components} | {b.get("id") for b in buses}

    def dump(model) -> dict:
        return model.model_dump(mode="json", exclude_none=True, exclude_defaults=True)

    def unique(base: str) -> str:
        if base not in ids:
            ids.add(base)
            return base
        n = 2
        while f"{base}{n}" in ids:
            n += 1
        ids.add(f"{base}{n}")
        return f"{base}{n}"

    def component(**fields) -> str:
        c = dump(Component(**fields))
        components.append({**c, "params": c.get("params", {})})
        return fields["id"]

    def connect(cid: str, role: str, target: dict) -> None:
        connections.append(dump(Connection(component_id=cid, pin_role=role, target=target)))

    def power(cid: str) -> None:
        if "3V3" in rails:
            connect(cid, "VCC", {"kind": "rail", "rail": "3V3"})
        if "GND" in rails:
            connect(cid, "GND", {"kind": "rail", "rail": "GND"})

    gps = lw.get("gps")
    if gps is not None and "uart_gps" not in present:
        bus_id = unique("gps_uart")
        buses.append(dump(Bus(id=bus_id, type="uart", rx=gps["rx_pin"], tx=gps["tx_pin"],
                              baud_rate=gps.get("baud", 9600))))
        cid = component(id=unique(_GPS_ID), library_id="uart_gps", label="GPS")
        power(cid)
        connect(cid, "TX", {"kind": "bus", "bus_id": bus_id})
        connect(cid, "RX", {"kind": "bus", "bus_id": bus_id})

    dht22 = lw.get("dht22")
    if dht22 is not None and "dht" not in present:
        cid = component(id=unique(_DHT_ID), library_id="dht", label="DHT", params={"model": "DHT22"})
        power(cid)
        connect(cid, "DATA", {"kind": "gpio", "pin": dht22["pin"]})

    oled = lw.get("oled")
    if oled is not None and oled.get("enabled", True) and "ssd1306" not in present:
        bus_id = next((b["id"] for b in buses if b.get("type") == "i2c"), None)
        if bus_id is None and i2c_default.get("sda") and i2c_default.get("scl"):
            bus_id = unique("i2c0")
            buses.append(dump(Bus(id=bus_id, type="i2c",
                                  sda=i2c_default["sda"], scl=i2c_default["scl"])))
        ob = onboard.get("oled_ssd1306") or {}
        params: dict = {"address": ob.get("address", "0x3C")}
        if ob.get("vext"):
            params["vext_pin"] = ob["vext"]
        cid = component(id=unique(_OLED_ID), library_id="ssd1306", label="OLED", params=params)
        power(cid)
        if bus_id is not None:
            connect(cid, "SDA", {"kind": "bus", "bus_id": bus_id})
            connect(cid, "SCL", {"kind": "bus", "bus_id": bus_id})
        if ob.get("reset"):
            connect(cid, "RESET", {"kind": "gpio", "pin": ob["reset"]})

    out = dict(raw)
    out["components"] = components
    out["buses"] = buses
    out["connections"] = connections
    out["lorawan"] = {k: v for k, v in lw.items() if k not in _SUGAR_FIELDS}
    return out


STEPS: list[Step] = [
    Step("0.1", "0.2", "lower_lorawan_sugar", _lower_lorawan_sugar),
    Step("0.2", "0.3", "drop_unread_fields", _drop_unread_fields),
    # The 0.2 and 0.3 models still accepted the blocks; 1.0 drops them.
    Step("0.3", "1.0", "retire_lorawan_sugar", _lower_lorawan_sugar),
]


def _free_bus_id(bus: dict, taken: set) -> str:
    from wirestudio.model import generated_bus_id

    n = 0
    while (new := generated_bus_id(str(bus.get("type") or "bus"), n)) in taken:
        n += 1
    return new


# `library_id` and `module_id` name library entries, which may share an
# instance's id (a `bh1750` of library `bh1750`); they never reference one.
_NOT_REFERENCES = frozenset({"library_id", "module_id"})


def _apply_id_renames(raw: dict, renames: dict[str, str]) -> dict:
    """The document with `renames` applied to component and bus ids and to
    every reference to one: `connections[].component_id`, connection targets,
    automations, `lorawan.payload[].sensor`, and any `*_id` value in params
    or esphome_extras. Returns `raw` itself when there is nothing to do."""
    if not renames:
        return raw

    def walk(node, key=None):
        if isinstance(node, dict):
            return {k: walk(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, key) for v in node]
        if isinstance(node, str) and key and (
                (key.endswith("_id") and key not in _NOT_REFERENCES) or key == "sensor"):
            return renames.get(node, node)
        return node

    out = walk(raw)
    for section in ("components", "buses"):
        out[section] = [{**x, "id": renames.get(x["id"], x["id"])} if isinstance(x, dict) and "id" in x else x
                        for x in out.get(section) or []]
    return out


def _rename_reserved_bus_ids(raw: dict, library: "Callable[[], Library]") -> dict:
    """A bus named after an ESPHome peripheral (`spi0`, `uart0`, ...)
    makes ESPHome refuse the whole render. Older onboard seeding wrote
    exactly that, so rename the bus the way the studio names one now
    (`spi_bus0`) and follow every reference."""
    from wirestudio.model import RESERVED_BUS_IDS

    buses = [b for b in raw.get("buses") or [] if isinstance(b, dict)]
    taken = {b.get("id") for b in buses}
    renames: dict[str, str] = {}
    for b in buses:
        if b.get("id") in RESERVED_BUS_IDS:
            renames[b["id"]] = _free_bus_id(b, taken)
            taken.add(renames[b["id"]])
    return _apply_id_renames(raw, renames)


def _rename_integration_name_ids(raw: dict, library: "Callable[[], Library]") -> dict:
    """A component or bus whose id names an ESPHome integration the design
    loads (`bh1750` on a BH1750, `i2c` on an I2C bus) makes ESPHome refuse
    the render; the studio accepted such ids before 0.47.0. Rename it to
    the next free suffixed id and follow every reference. A design that
    does not render is left alone; the render reports it."""
    from pydantic import ValidationError

    from wirestudio.generate.yaml_gen import esphome_id_conflicts, esphome_integration_names
    from wirestudio.model import Design

    components = [c for c in raw.get("components") or [] if isinstance(c, dict)]
    buses = [b for b in raw.get("buses") or [] if isinstance(b, dict)]
    names = esphome_integration_names()
    if not any(x.get("id") in names for x in components + buses):
        return raw
    try:
        conflicts = esphome_id_conflicts(Design.model_validate(raw), library())
    except (ValidationError, FileNotFoundError, ValueError):
        return raw
    taken = {x.get("id") for x in components + buses}
    renames: dict[str, str] = {}
    for c in components:
        if c.get("id") in conflicts:
            n = 1
            while (new := f"{c['id']}_{n}") in taken:
                n += 1
            renames[c["id"]] = new
            taken.add(new)
    for b in buses:
        if b.get("id") in conflicts:
            renames[b["id"]] = _free_bus_id(b, taken)
            taken.add(renames[b["id"]])
    return _apply_id_renames(raw, renames)


REPAIRS: list[tuple[str, "Callable[[dict, Callable[[], Library]], dict]"]] = [
    ("rename_reserved_bus_ids", _rename_reserved_bus_ids),
    ("rename_integration_name_ids", _rename_integration_name_ids),
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
    known = {s.from_version for s in STEPS} | {CURRENT_SCHEMA_VERSION}
    if version not in known:
        raise MigrationError(
            f"schema_version {version!r} is not one this wirestudio can read "
            f"(it writes {CURRENT_SCHEMA_VERSION}); the design may come from a newer release"
        )
    def resolved() -> "Library":
        nonlocal library
        if library is None:
            from wirestudio.library import default_library
            library = default_library()
        return library

    document = raw
    while version != CURRENT_SCHEMA_VERSION:
        step = next(s for s in STEPS if s.from_version == version)
        document = {**step.apply(document, resolved()), "schema_version": step.to_version}
        result.applied.append(step.name)
        version = step.to_version
    for name, repair in REPAIRS:
        repaired = repair(document, resolved)
        if repaired is not document:
            document = repaired
            result.applied.append(name)
    result.document = document
    result.to_version = version
    return result


def load_design(raw: dict, library=None) -> "Design":
    """`raw` brought to the current version and validated. Raises
    MigrationError or pydantic's ValidationError."""
    from wirestudio.model import Design

    return Design.model_validate(migrate(raw, library).document)


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
