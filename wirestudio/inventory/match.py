"""Match board parts against the drawer.

Two kinds of thing come off a board and they match differently. A
semiconductor carries an MPN (`IRF4905`) and matches an inventory part
by name. A passive carries a value (`470`, `100nF`) and matches by
magnitude, because `10k`, `10K` and `10000` are the same resistor.

Which one a part is comes from its reference designator: `assign_refs`
builds those from each subcircuit part's `ref_prefix`, so `R3` is a
resistor by construction rather than by guessing at its value.

Common passive values count as on hand even when the drawer does not
list them -- nobody inventories 10k resistors -- but they report as
`assumed` rather than `have`, so the distinction stays visible.
"""
from __future__ import annotations

import re

# Resistor notation: 470, 470R, 4R7, 1k, 4k7, 1M, "470 ohm".
# Capacitor notation: 100nF, 100n, 0.1uF, 22pF.
_R_MULT = {"": 1.0, "r": 1.0, "k": 1e3, "m": 1e6}
_C_MULT = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3}
_L_MULT = {"": 1.0, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3}

_VALUE_FAMILIES = ("resistor", "capacitor", "inductor")

# Designator prefix -> what the part is. Anything else (J, and any
# prefix a future subcircuit introduces) is not something a parts
# drawer tracks, and reports as `untracked` rather than as missing.
_REF_FAMILY = {
    "R": "resistor", "C": "capacitor", "L": "inductor",
    "D": "diode", "Q": "transistor", "U": "ic", "VR": "regulator",
}

_E12 = (10, 12, 15, 18, 22, 27, 33, 39, 47, 56, 68, 82)


def _common_resistors() -> frozenset[float]:
    """E12 from 1R to 8.2M -- the range a hobby drawer actually spans."""
    return frozenset(
        round(base * (10 ** k) / 10, 6)
        for base in _E12
        for k in range(7)
    )


_COMMON_RESISTORS = _common_resistors()
_COMMON_CAPACITORS = frozenset({
    22e-12, 100e-12, 1e-9, 10e-9, 22e-9, 100e-9, 220e-9,
    1e-6, 4.7e-6, 10e-6, 47e-6, 100e-6, 220e-6, 470e-6, 1000e-6,
})


def family_for_ref(ref: str) -> str:
    """Part family from a reference designator ('R3' -> resistor)."""
    prefix = re.match(r"^([A-Za-z]+)", ref or "")
    if not prefix:
        return ""
    letters = prefix.group(1).upper()
    return _REF_FAMILY.get(letters, _REF_FAMILY.get(letters[:1], ""))


def matches_by_value(family: str) -> bool:
    return family in _VALUE_FAMILIES


def normalize_value(raw: str, family: str) -> float | None:
    """A passive's value as a number (ohms / farads / henries).

    Returns None when the text isn't a value in that family's notation,
    which is the normal answer for a semiconductor's MPN.
    """
    text = (raw or "").strip().lower()
    if not text:
        return None
    text = re.sub(r"\s*(ohms?|Ω|f|h)$", "", text)
    text = text.replace(" ", "")
    if not text:
        return None

    mult = {"resistor": _R_MULT, "capacitor": _C_MULT, "inductor": _L_MULT}.get(family)
    if mult is None:
        return None

    # Embedded-letter decimal: 4k7 = 4700, 4r7 = 4.7, 2n2 = 2.2nF.
    embedded = re.fullmatch(r"(\d+)([a-zµ])(\d+)", text)
    if embedded:
        unit = embedded.group(2)
        if unit not in mult:
            return None
        whole, frac = embedded.group(1), embedded.group(3)
        return float(f"{whole}.{frac}") * mult[unit]

    plain = re.fullmatch(r"([\d.]+)([a-zµ]?)", text)
    if not plain:
        return None
    try:
        number = float(plain.group(1))
    except ValueError:
        return None
    unit = plain.group(2)
    if unit not in mult:
        return None
    return number * mult[unit]


def is_common(value: float | None, family: str) -> bool:
    """A value nobody bothers to inventory."""
    if value is None:
        return False
    if family == "resistor":
        return any(abs(value - c) < c * 1e-6 for c in _COMMON_RESISTORS)
    if family == "capacitor":
        return any(abs(value - c) < c * 1e-6 for c in _COMMON_CAPACITORS)
    return False
