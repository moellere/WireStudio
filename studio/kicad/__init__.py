"""KiCad schematic export (0.9). v1 emits a SKiDL Python script the
user runs locally; PCB layout is deferred to 1.0+."""
from studio.kicad.generator import generate_skidl

__all__ = ["generate_skidl"]
