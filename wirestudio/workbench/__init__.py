"""Universal Embedded Workbench client — the studio's hardware truth layer.

Thin client only: the workbench owns slots, serial and RF. The studio
uploads an image and reads status; it never re-implements the bench.
"""
from wirestudio.workbench.client import (
    Slot,
    WorkbenchClient,
    WorkbenchUnavailable,
)

__all__ = ["Slot", "WorkbenchClient", "WorkbenchUnavailable"]
