from __future__ import annotations

from wirestudio.library import Library
from wirestudio.model import Design
from wirestudio.targets.base import TargetPlugin, register


class EsphomeTarget(TargetPlugin):
    """The default target: renders ESPHome YAML + an ASCII wiring diagram."""

    id = "esphome"

    def board_ids(self, library: Library) -> list[str]:
        return sorted(b.id for b in library.list_boards())

    def component_ids(self, library: Library) -> list[str]:
        # Every library component carries an esphome block, so all are
        # selectable for the esphome target.
        return sorted(c.id for c in library.list_components())

    def generate(self, design: Design, library: Library) -> dict[str, str]:
        from wirestudio.generate import yaml_gen, ascii_gen
        return {
            "firmware.yaml": yaml_gen.render_yaml(design, library),
            "wiring.txt": ascii_gen.render_ascii(design, library),
        }


register(EsphomeTarget())
