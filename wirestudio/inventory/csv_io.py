"""CSV import/export for the parts inventory.

Export is a flat round-trip of every field. Import is deliberately
lenient, because the input is a real spreadsheet rather than something
this tool wrote: it finds the header wherever it starts, maps the
column names people actually use, and -- the part that matters --
**never drops a row silently**. Anything it cannot turn into an entry
comes back in `rejected` with a reason and the raw row.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from wirestudio.inventory.store import FAMILIES, InventoryEntry

FIELDS = [
    "library_id", "mpn", "kind", "quantity", "min_quantity", "location", "note",
    "family", "polarity", "package", "pinout", "value", "v_max", "i_max",
]

# Normalised header -> entry field. Matched exactly first, then by
# prefix (longest alias wins) so "pinout (flat face L-to-R)" and
# "notes & key specs" land without listing every spreadsheet's phrasing.
_ALIASES: dict[str, str] = {
    "part": "mpn", "part number": "mpn", "mpn": "mpn", "part no": "mpn",
    "library id": "library_id", "library_id": "library_id",
    "kind": "kind",
    "family": "family", "type": "family",
    "polarity": "polarity", "polarity type": "polarity",
    "qty": "quantity", "quantity": "quantity", "total qty": "quantity",
    "on hand": "quantity", "count": "quantity", "stock": "quantity",
    "min qty": "min_quantity", "min quantity": "min_quantity",
    "reorder": "min_quantity",
    "location": "location", "kit location": "location",
    "kit locations": "location", "bin": "location", "drawer": "location",
    "package": "package", "case": "package",
    "pinout": "pinout", "pin order": "pinout",
    "value": "value",
    "note": "note", "notes": "note", "comment": "note",
    "description": "note",
}

_IDENTITY_FIELDS = ("mpn", "library_id")

# Summary rows ("Total Inventory, ..., 720") parse as a part otherwise:
# they have a label and a quantity. Rejected, not dropped, so an import
# that misreads one is visible in the result.
_SUMMARY_LABELS = {"total", "totals", "subtotal", "grand total", "sum",
                   "total inventory"}

_FAMILY_KEYWORDS = [
    ("darlington", "bjt"), ("bjt", "bjt"), ("transistor", "bjt"),
    ("mosfet", "mosfet"), ("fet", "mosfet"),
    ("regulator", "regulator"), ("resistor", "resistor"),
    ("capacitor", "capacitor"), ("inductor", "inductor"),
    ("diode", "diode"), ("connector", "connector"), ("header", "connector"),
]

_POLARITY_MAP = {
    "npn": "npn", "pnp": "pnp",
    "n-channel": "n", "p-channel": "p", "nchannel": "n", "pchannel": "p",
    "n channel": "n", "p channel": "p", "n": "n", "p": "p",
}

# Leading "55V, 110A" / "-55V, -74A" on a spec note. Magnitudes only --
# polarity already carries the sign.
_VA_RE = re.compile(r"^\s*(-?[\d.]+)\s*V\s*,\s*(-?[\d.]+)\s*A", re.IGNORECASE)


@dataclass
class RejectedRow:
    row: int
    reason: str
    raw: dict[str, str] = field(default_factory=dict)


@dataclass
class ImportResult:
    entries: list[InventoryEntry] = field(default_factory=list)
    rejected: list[RejectedRow] = field(default_factory=list)
    header_row: int = 0


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _field_for(header: str) -> str:
    key = _norm(header)
    if not key:
        return ""
    if key in _ALIASES:
        return _ALIASES[key]
    for alias in sorted(_ALIASES, key=len, reverse=True):
        if key.startswith(alias):
            return _ALIASES[alias]
    return ""


def _family(raw: str) -> str:
    low = _norm(raw)
    if low in FAMILIES:
        return low
    for needle, fam in _FAMILY_KEYWORDS:
        if needle in low:
            return fam
    return "other" if low else ""


def _polarity(raw: str) -> str:
    low = (raw or "").strip().lower()
    return _POLARITY_MAP.get(low, low)


def _int(raw: str) -> int:
    digits = re.sub(r"[^0-9-]", "", (raw or "").strip())
    return int(digits) if digits and digits != "-" else 0


def entries_to_csv(entries: list[InventoryEntry]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    for e in entries:
        writer.writerow({f: ("" if getattr(e, f) is None else getattr(e, f))
                         for f in FIELDS})
    return buf.getvalue()


def entries_from_csv(text: str) -> ImportResult:
    """Parse spreadsheet rows into entries.

    Rows before the header are preamble and ignored; `header_row` says
    where parsing started. Every row after it produces either an entry
    or a `RejectedRow`.
    """
    rows = list(csv.reader(io.StringIO(text)))
    result = ImportResult()

    header_idx, columns = -1, {}
    for i, row in enumerate(rows):
        mapped = {j: _field_for(cell) for j, cell in enumerate(row)}
        mapped = {j: f for j, f in mapped.items() if f}
        if any(f in _IDENTITY_FIELDS for f in mapped.values()):
            header_idx, columns = i, mapped
            break
    if header_idx < 0:
        result.rejected.append(RejectedRow(
            row=1, reason="no header row naming a part / mpn / library_id column"))
        return result
    result.header_row = header_idx + 1

    for i, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        raw = {columns[j]: row[j].strip()
               for j in columns if j < len(row) and row[j].strip()}
        if not raw:
            continue  # blank spacer row
        mpn = raw.get("mpn", "")
        library_id = raw.get("library_id", "")
        if not mpn and not library_id:
            result.rejected.append(RejectedRow(i, "no part name or library id", raw))
            continue
        if _norm(mpn or library_id) in _SUMMARY_LABELS:
            result.rejected.append(RejectedRow(i, "looks like a summary row", raw))
            continue

        kind = raw.get("kind", "").strip().lower()
        if not kind:
            kind = "part" if mpn else "component"
        note = raw.get("note", "")
        v_max = i_max = None
        match = _VA_RE.match(note)
        if match:
            v_max, i_max = abs(float(match.group(1))), abs(float(match.group(2)))

        try:
            entry = InventoryEntry(
                library_id=library_id if kind != "part" else "",
                mpn=mpn if kind == "part" else "",
                kind=kind,
                quantity=_int(raw.get("quantity", "")),
                min_quantity=_int(raw.get("min_quantity", "")),
                location=raw.get("location", ""),
                note=note,
                family=_family(raw.get("family", "")),
                polarity=_polarity(raw.get("polarity", "")),
                package=raw.get("package", ""),
                pinout=raw.get("pinout", ""),
                value=raw.get("value", ""),
                v_max=v_max,
                i_max=i_max,
            )
        except (ValueError, TypeError) as exc:
            result.rejected.append(RejectedRow(i, str(exc), raw))
            continue
        result.entries.append(entry)
    return result
