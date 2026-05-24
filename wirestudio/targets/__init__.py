from __future__ import annotations

from wirestudio.targets.base import TargetPlugin, get_target, register, target_ids

# Importing the target modules registers them as a side effect.
from wirestudio.targets import esphome as _esphome  # noqa: F401
from wirestudio.targets import lorawan as _lorawan  # noqa: F401

__all__ = ["TargetPlugin", "get_target", "register", "target_ids"]
