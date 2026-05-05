"""Enclosure helpers (0.8).

v1 ships the parametric OpenSCAD generator; v2 adds the
Thingiverse / Printables search relay. The two surfaces share the
board's `enclosure:` metadata as input.
"""
from wirestudio.enclosure.openscad import EnclosureUnavailable, generate_scad
from wirestudio.enclosure.search import (
    EnclosureHit,
    PrintablesSource,
    SearchResponse,
    SourceStatus,
    ThingiverseSource,
    default_sources,
    query_for_board,
    search_enclosures,
)

__all__ = [
    "EnclosureUnavailable",
    "generate_scad",
    "EnclosureHit",
    "SearchResponse",
    "SourceStatus",
    "ThingiverseSource",
    "PrintablesSource",
    "default_sources",
    "query_for_board",
    "search_enclosures",
]
