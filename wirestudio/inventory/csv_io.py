"""CSV import/export for the local inventory.

A flat, spreadsheet-friendly round-trip: `library_id,kind,quantity,
min_quantity,location,note`. Import is lenient about column order and
blank lines but strict about each row validating as an `InventoryEntry`.
"""
from __future__ import annotations

import csv
import io

from wirestudio.inventory.store import InventoryEntry

FIELDS = ["library_id", "kind", "quantity", "min_quantity", "location", "note"]


def entries_to_csv(entries: list[InventoryEntry]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    for e in entries:
        writer.writerow({
            "library_id": e.library_id, "kind": e.kind, "quantity": e.quantity,
            "min_quantity": e.min_quantity, "location": e.location, "note": e.note,
        })
    return buf.getvalue()


def entries_from_csv(text: str) -> list[InventoryEntry]:
    """Parse CSV rows into entries. Blank `library_id` rows are skipped;
    a row that fails `InventoryEntry` validation raises ValueError naming
    the offending line."""
    out: list[InventoryEntry] = []
    reader = csv.DictReader(io.StringIO(text))
    for i, row in enumerate(reader, start=2):  # row 1 is the header
        library_id = (row.get("library_id") or "").strip()
        if not library_id:
            continue
        try:
            out.append(InventoryEntry(
                library_id=library_id,
                kind=(row.get("kind") or "component").strip() or "component",
                quantity=int(row.get("quantity") or 0),
                min_quantity=int(row.get("min_quantity") or 0),
                location=(row.get("location") or "").strip(),
                note=(row.get("note") or "").strip(),
            ))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"row {i}: {exc}") from exc
    return out
