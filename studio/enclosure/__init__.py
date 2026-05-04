"""Enclosure helpers (0.8). v1 ships the parametric OpenSCAD generator;
v2 will add the Thingiverse / Printables search relay."""
from studio.enclosure.openscad import EnclosureUnavailable, generate_scad

__all__ = ["EnclosureUnavailable", "generate_scad"]
