from __future__ import annotations

from wirestudio.library import Library
from wirestudio.targets.base import TargetPlugin, register


class EsphomeTarget(TargetPlugin):
    """The default target. Every board is selectable; generation still runs
    through ``wirestudio.generate`` directly (the API calls it), so there is
    no generate() method here until a second generator forces the seam."""

    id = "esphome"

    def board_ids(self, library: Library) -> list[str]:
        return sorted(b.id for b in library.list_boards())


register(EsphomeTarget())
