"""Constraint-satisfaction layer.

Currently lightweight: a pin-assignment solver that fills in unbound
connections (kind=gpio with empty pin, kind=bus with empty bus_id,
kind=expander_pin with empty expander_id) using the board's available
GPIOs and the design's existing buses.

In future phases this is the natural home for richer reasoning:
recommendation mode, voltage/level-shifter checks, deterministic strict
mode, multi-objective optimization. v1 is intentionally a single-pass
greedy backtracker -- the search space is tiny (a few dozen pins).
"""

from wirestudio.csp.compatibility import CompatibilityWarning, check_pin_compatibility
from wirestudio.csp.pin_solver import SolveResult, solve_pins

__all__ = [
    "solve_pins", "SolveResult",
    "check_pin_compatibility", "CompatibilityWarning",
]
