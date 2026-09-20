"""File-backed parts inventory.

One JSON file (`inventory.json`) holds the whole inventory: the user is a
single operator with a single parts drawer, so there's no per-user
namespacing (same call as the active-design tracker).

Two kinds of thing live here. A `component` or `module` entry names a
library id -- something the studio can place in a design directly. A
`part` entry names an MPN that has no library file at all: the
transistors, MOSFETs, passives and regulators a drawer is mostly made
of. Parts key under `part:<mpn>` so a drawer part called `adc` can never
collide with the `adc` component.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Protocol

from wirestudio.designs.store import DESIGNS_DIR_DEFAULT

INVENTORY_PATH_DEFAULT = DESIGNS_DIR_DEFAULT.parent / "inventory.json"

_KINDS = ("component", "module", "part")

# Families a `part` can belong to. Coarse on purpose: this is what
# substitution matching compares, not a taxonomy.
FAMILIES = (
    "bjt", "mosfet", "resistor", "capacitor", "inductor", "diode",
    "regulator", "connector", "ic", "other",
)


@dataclass
class InventoryEntry:
    library_id: str = ""  # component / module kinds
    mpn: str = ""  # part kind
    kind: str = "component"  # component | module | part
    quantity: int = 0
    min_quantity: int = 0  # low-stock threshold; 0 = no threshold
    location: str = ""
    note: str = ""
    # Part specs. All optional -- a drawer row with only a quantity is
    # still worth having. v_max / i_max are magnitudes; `polarity`
    # carries the sign for PNP and P-channel parts.
    family: str = ""
    polarity: str = ""
    package: str = ""
    pinout: str = ""
    value: str = ""
    v_max: Optional[float] = None
    i_max: Optional[float] = None

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"kind must be one of {_KINDS}, got {self.kind!r}")
        if self.kind == "part":
            if not self.mpn or not isinstance(self.mpn, str):
                raise ValueError("a part entry needs an mpn")
            if self.library_id:
                raise ValueError("a part entry has no library_id")
        else:
            if not self.library_id or not isinstance(self.library_id, str):
                raise ValueError(f"a {self.kind} entry needs a library_id")
            if self.mpn:
                raise ValueError(f"a {self.kind} entry has no mpn")
        if not isinstance(self.quantity, int) or self.quantity < 0:
            raise ValueError("quantity must be a non-negative integer")
        if not isinstance(self.min_quantity, int) or self.min_quantity < 0:
            raise ValueError("min_quantity must be a non-negative integer")
        if self.family and self.family not in FAMILIES:
            raise ValueError(f"family must be one of {FAMILIES}, got {self.family!r}")
        for field in ("v_max", "i_max"):
            v = getattr(self, field)
            if v is not None and (not isinstance(v, (int, float)) or v < 0):
                raise ValueError(f"{field} must be a non-negative number")

    @property
    def key(self) -> str:
        """Store key. Parts are namespaced so an MPN can't shadow a library id."""
        return f"part:{self.mpn}" if self.kind == "part" else self.library_id

    @property
    def label(self) -> str:
        return self.mpn if self.kind == "part" else self.library_id

    @property
    def low_stock(self) -> bool:
        """On hand at or below the reorder threshold (and a threshold is set)."""
        return self.min_quantity > 0 and self.quantity <= self.min_quantity


def part_key(mpn: str) -> str:
    return f"part:{mpn}"


class InventoryStore(Protocol):
    def list(self) -> list[InventoryEntry]: ...
    def get(self, key: str) -> Optional[InventoryEntry]: ...
    def set(self, entry: InventoryEntry) -> InventoryEntry: ...
    def remove(self, key: str) -> bool: ...


class FileInventoryStore(InventoryStore):
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else INVENTORY_PATH_DEFAULT

    def _read(self) -> dict[str, InventoryEntry]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
        out: dict[str, InventoryEntry] = {}
        for raw in data.get("entries", []):
            try:
                entry = InventoryEntry(**raw)
            except (TypeError, ValueError):
                continue
            out[entry.key] = entry
        return out

    def _write(self, entries: dict[str, InventoryEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(entries.values(), key=lambda e: e.key)
        payload = {
            "schema_version": "0.1",
            # Empty optionals are dropped so a drawer of plain component
            # rows doesn't carry seven blank part fields each.
            "entries": [
                {k: v for k, v in asdict(e).items() if v not in ("", None)}
                for e in ordered
            ],
        }
        self.path.write_text(json.dumps(payload, indent=2))

    def list(self) -> list[InventoryEntry]:
        return sorted(self._read().values(), key=lambda e: e.key)

    def get(self, key: str) -> Optional[InventoryEntry]:
        return self._read().get(key)

    def set(self, entry: InventoryEntry) -> InventoryEntry:
        entries = self._read()
        entries[entry.key] = entry
        self._write(entries)
        return entry

    def remove(self, key: str) -> bool:
        entries = self._read()
        if key not in entries:
            return False
        del entries[key]
        self._write(entries)
        return True


def default_inventory_store() -> FileInventoryStore:
    """Inventory store honouring the `INVENTORY_PATH` env override."""
    return FileInventoryStore(path=os.environ.get("INVENTORY_PATH") or None)
