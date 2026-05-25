"""File-backed component inventory.

One JSON file (`inventory.json`) holds the whole inventory: the user is a
single operator with a single parts drawer, so there's no per-user
namespacing (same call as the active-design tracker). Each entry is a
library id (a component or a composite module), a quantity, and optional
free-text location/note.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Protocol

from wirestudio.designs.store import DESIGNS_DIR_DEFAULT

INVENTORY_PATH_DEFAULT = DESIGNS_DIR_DEFAULT.parent / "inventory.json"

_KINDS = ("component", "module")


@dataclass
class InventoryEntry:
    library_id: str
    kind: str = "component"  # component | module
    quantity: int = 0
    location: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not self.library_id or not isinstance(self.library_id, str):
            raise ValueError("inventory entry needs a library_id")
        if self.kind not in _KINDS:
            raise ValueError(f"kind must be one of {_KINDS}, got {self.kind!r}")
        if not isinstance(self.quantity, int) or self.quantity < 0:
            raise ValueError("quantity must be a non-negative integer")


class InventoryStore(Protocol):
    def list(self) -> list[InventoryEntry]: ...
    def get(self, library_id: str) -> Optional[InventoryEntry]: ...
    def set(self, entry: InventoryEntry) -> InventoryEntry: ...
    def remove(self, library_id: str) -> bool: ...


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
            out[entry.library_id] = entry
        return out

    def _write(self, entries: dict[str, InventoryEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(entries.values(), key=lambda e: e.library_id)
        payload = {"schema_version": "0.1", "entries": [asdict(e) for e in ordered]}
        self.path.write_text(json.dumps(payload, indent=2))

    def list(self) -> list[InventoryEntry]:
        return sorted(self._read().values(), key=lambda e: e.library_id)

    def get(self, library_id: str) -> Optional[InventoryEntry]:
        return self._read().get(library_id)

    def set(self, entry: InventoryEntry) -> InventoryEntry:
        entries = self._read()
        entries[entry.library_id] = entry
        self._write(entries)
        return entry

    def remove(self, library_id: str) -> bool:
        entries = self._read()
        if library_id not in entries:
            return False
        del entries[library_id]
        self._write(entries)
        return True


def default_inventory_store() -> FileInventoryStore:
    """Inventory store honouring the `INVENTORY_PATH` env override."""
    return FileInventoryStore(path=os.environ.get("INVENTORY_PATH") or None)
