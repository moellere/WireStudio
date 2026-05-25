"""Local component inventory -- what parts the user physically has on hand.

A single-user, single-inventory store (one `inventory.json`) plus a
design-vs-inventory cross-check. Feeds the recommender so designs prefer
parts already in the drawer.
"""
from wirestudio.inventory.check import (
    InventoryLine,
    InventoryReport,
    check_inventory,
)
from wirestudio.inventory.csv_io import entries_from_csv, entries_to_csv
from wirestudio.inventory.store import (
    FileInventoryStore,
    InventoryEntry,
    InventoryStore,
)

__all__ = [
    "InventoryEntry",
    "InventoryStore",
    "FileInventoryStore",
    "InventoryLine",
    "InventoryReport",
    "check_inventory",
    "entries_to_csv",
    "entries_from_csv",
]
