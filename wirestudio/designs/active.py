"""Server-side "active design" tracker.

A single string slot that records which design id the user is currently
working on. The browser writes it when the user selects a saved design;
MCP tools read it as the default for `design_id` so a chat like "add a
BME280 to this design" resolves against whatever the browser is showing.

Single-operator homelab assumption: one tracker per server process,
shared across browser tabs and MCP clients. A multi-user deployment
would key this by session, but that's out of scope until/unless
wirestudio grows past a single-operator surface.

The tracker is just a mutable string box. Concurrency-safe because the
underlying assignment is atomic in CPython; no lock needed for a single
slot.
"""
from __future__ import annotations

from typing import Optional


class ActiveDesignTracker:
    """Holds the currently-active design id."""

    def __init__(self, initial: Optional[str] = None) -> None:
        self._id: Optional[str] = initial

    def get(self) -> Optional[str]:
        return self._id

    def set(self, design_id: Optional[str]) -> None:
        """Set or clear the active design id. Empty string normalizes to None."""
        self._id = design_id if design_id else None

    def clear(self) -> None:
        self._id = None
