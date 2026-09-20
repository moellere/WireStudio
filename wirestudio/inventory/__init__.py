"""Local parts inventory -- what the user physically has on hand.

A single-user, single-inventory store (one `inventory.json`) plus a
design-vs-inventory cross-check. Holds library components and modules by
library id, and discrete parts (transistors, passives, regulators) by
MPN. Feeds the recommender so designs prefer parts already in the drawer.
"""
from wirestudio.inventory.check import (
    InventoryLine,
    InventoryReport,
    Substitute,
    check_inventory,
    find_substitutes,
    subcircuit_coverage,
)
from wirestudio.inventory.csv_io import (
    ImportResult,
    RejectedRow,
    entries_from_csv,
    entries_to_csv,
)
from wirestudio.inventory.store import (
    FAMILIES,
    FileInventoryStore,
    InventoryEntry,
    InventoryStore,
    part_key,
)

__all__ = [
    "FAMILIES",
    "FileInventoryStore",
    "ImportResult",
    "InventoryEntry",
    "InventoryLine",
    "InventoryReport",
    "InventoryStore",
    "RejectedRow",
    "Substitute",
    "check_inventory",
    "find_substitutes",
    "subcircuit_coverage",
    "entries_from_csv",
    "entries_to_csv",
    "part_key",
]
