"""Pin assignment solver.

Treats the design as a CSP whose variables are the *unbound* connections:
- gpio with empty pin -> pick a board GPIO matching the library pin's kind
- bus with empty bus_id -> pick a design bus of the matching type
- expander_pin with empty expander_id -> pick an expander in the design

The solver is greedy with deterministic backtracking on conflicts -- the
problem size is small enough (typically <50 connections, <30 board pins)
that we don't need a real CSP library. Already-bound connections are
left untouched; conflicts among them are surfaced as warnings.

Pure: never mutates the input dict; returns a new design alongside the
diff and any warnings.
"""
from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from studio.library import Library, LibraryBoard, LibraryComponent, Pin


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class PinAssignment:
    component_id: str
    pin_role: str
    old_target: dict
    new_target: dict


@dataclass
class SolverWarning:
    level: str  # "info" / "warn" / "error"
    code: str
    text: str


@dataclass
class SolveResult:
    design: dict
    assigned: list[PinAssignment] = field(default_factory=list)
    unresolved: list[SolverWarning] = field(default_factory=list)
    warnings: list[SolverWarning] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Capability mapping
# ---------------------------------------------------------------------------

# Map a library pin kind to the set of board capabilities that satisfy it.
# Most digital pins just need `gpio`; analog needs `adc`. Special-purpose
# capabilities (i2s_dout, dac, pwm) are nice-to-have hints but not required
# in v1 -- we don't filter on them.
_PIN_KIND_TO_REQUIRED_CAPS: dict[str, set[str]] = {
    "digital_in": {"gpio"},
    "digital_out": {"gpio"},
    "analog_in": {"adc"},
    "i2s_dout": {"gpio"},
    # spi_cs is a per-component native pin (not part of the bus). Any GPIO works.
    "spi_cs": {"gpio"},
}

# Pins to *avoid* for given kinds (prefer pins without these tags).
_AVOID_FOR_OUTPUTS: set[str] = {"input_only"}


def _pin_capabilities(board: LibraryBoard, pin_name: str) -> list[str]:
    return board.gpio_capabilities.get(pin_name, [])


def _gpio_candidates_for_pin(
    board: LibraryBoard, lib_pin: Pin, prefer_unspecial: bool = True,
) -> list[str]:
    """Return board pins satisfying the library pin's required capability,
    sorted from most preferred to least."""
    required = _PIN_KIND_TO_REQUIRED_CAPS.get(lib_pin.kind, {"gpio"})
    is_output = lib_pin.kind in ("digital_out", "i2s_dout")
    is_analog_in = lib_pin.kind == "analog_in"
    is_classic_esp32 = getattr(board, "chip_variant", None) == "esp32"
    candidates: list[tuple[int, int, str]] = []
    for name, caps in board.gpio_capabilities.items():
        cap_set = set(caps)
        if not required.issubset(cap_set):
            continue
        if is_output and _AVOID_FOR_OUTPUTS & cap_set:
            continue
        # Prefer non-special pins. Boot strap pins (boot_high / boot_low) and
        # the legacy `boot` / `strap` / `builtin_led` tags all count as
        # "special" -- pickable as a last resort, never first.
        special = bool(cap_set & {
            "boot", "strap", "builtin_led",
            "boot_high", "boot_low",
            "serial_tx", "serial_rx",
        })
        # Secondary preference: for analog_in on a classic ESP32, prefer ADC1
        # pins (GPIO32-39) over ADC2 pins. ADC2 conflicts with WiFi -- see
        # the adc2_wifi_conflict check in compatibility.py.
        adc2_penalty = 0
        if is_analog_in and is_classic_esp32 and "adc2" in cap_set:
            adc2_penalty = 1
        candidates.append((1 if special else 0, adc2_penalty, name))
    candidates.sort()
    return [name for *_, name in candidates]


# ---------------------------------------------------------------------------
# Reading helpers (work on raw design dicts)
# ---------------------------------------------------------------------------

def _is_unbound(target: dict) -> bool:
    kind = target.get("kind")
    if kind == "gpio":
        return not target.get("pin")
    if kind == "bus":
        return not target.get("bus_id")
    if kind == "expander_pin":
        return not target.get("expander_id")
    return False


def _used_gpio_pins(design: dict) -> set[str]:
    used = set()
    for c in design.get("connections", []):
        t = c.get("target", {})
        if t.get("kind") == "gpio" and t.get("pin"):
            used.add(t["pin"])
    return used


def _used_expander_pins(design: dict) -> set[tuple[str, int]]:
    used = set()
    for c in design.get("connections", []):
        t = c.get("target", {})
        if t.get("kind") == "expander_pin" and t.get("expander_id") and t.get("number") is not None:
            used.add((t["expander_id"], int(t["number"])))
    return used


def _component_index(design: dict) -> dict[str, dict]:
    return {c["id"]: c for c in design.get("components", [])}


def _bus_index_by_type(design: dict) -> dict[str, list[str]]:
    by_type: dict[str, list[str]] = defaultdict(list)
    for b in design.get("buses", []):
        by_type[b.get("type")].append(b["id"])
    return dict(by_type)


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

def solve_pins(design_in: dict, library: Library) -> SolveResult:
    """Fill in unbound connections greedily. Pure: returns a new design dict."""
    design = copy.deepcopy(design_in)

    board_lib_id = (design.get("board") or {}).get("library_id")
    if not board_lib_id:
        return SolveResult(design=design, warnings=[SolverWarning(
            level="error", code="no_board",
            text="Design has no board.library_id; cannot solve pins.",
        )])

    try:
        board = library.board(board_lib_id)
    except FileNotFoundError as e:
        return SolveResult(design=design, warnings=[SolverWarning(
            level="error", code="unknown_board", text=str(e),
        )])

    components_by_id = _component_index(design)
    library_components: dict[str, LibraryComponent] = {}
    for c in components_by_id.values():
        try:
            library_components[c["id"]] = library.component(c["library_id"])
        except FileNotFoundError:
            # Caller will see the unknown component when they try to render;
            # skip it here and continue solving the rest.
            continue

    expanders = {
        cid: lib for cid, lib in library_components.items()
        if lib.category == "io_expander"
    }
    expander_pin_count = {
        cid: max((p.role for p in lib.electrical.pins if p.role.isdigit()), default=None) or _expander_size_for(cid, library_components)
        for cid, lib in expanders.items()
    }

    used_gpios = _used_gpio_pins(design)
    used_expander_pins = _used_expander_pins(design)
    buses_by_type = _bus_index_by_type(design)

    assigned: list[PinAssignment] = []
    unresolved: list[SolverWarning] = []

    # Apply locked_pins first. The user's manual pin choices override the
    # solver's preferences; we either fill an empty target with the locked
    # pin or flag a divergence between the bound target and the lock. Locks
    # only apply to gpio targets today (the dict value is a board pin name);
    # bus/expander locks are not yet defined.
    lock_warnings = _apply_locked_pins(
        design, components_by_id, library_components, used_gpios, assigned,
    )
    unresolved.extend(lock_warnings)

    for conn in design.get("connections", []):
        target = conn.get("target") or {}
        if not _is_unbound(target):
            continue

        comp = components_by_id.get(conn["component_id"])
        if not comp:
            unresolved.append(SolverWarning(
                level="warn", code="unknown_component",
                text=f"connection references unknown component '{conn['component_id']}'",
            ))
            continue

        lib_comp = library_components.get(comp["id"])
        if not lib_comp:
            unresolved.append(SolverWarning(
                level="warn", code="unknown_library_component",
                text=f"component '{comp['id']}' has unknown library_id '{comp['library_id']}'",
            ))
            continue

        lib_pin = next((p for p in lib_comp.electrical.pins if p.role == conn["pin_role"]), None)
        if not lib_pin:
            unresolved.append(SolverWarning(
                level="warn", code="unknown_pin_role",
                text=f"{comp['id']}.{conn['pin_role']} has no library entry",
            ))
            continue

        kind = target["kind"]
        if kind == "gpio":
            choice = _solve_gpio(board, lib_pin, used_gpios)
            if not choice:
                unresolved.append(SolverWarning(
                    level="warn", code="no_gpio_candidate",
                    text=f"no board GPIO satisfies {comp['id']}.{conn['pin_role']} ({lib_pin.kind})",
                ))
                continue
            old = dict(target)
            new = {"kind": "gpio", "pin": choice}
            conn["target"] = new
            used_gpios.add(choice)
            assigned.append(PinAssignment(comp["id"], conn["pin_role"], old, new))

        elif kind == "bus":
            wanted = _bus_type_for_pin(lib_pin.kind)
            if not wanted:
                unresolved.append(SolverWarning(
                    level="warn", code="bus_pin_no_type",
                    text=f"can't determine bus type for {comp['id']}.{conn['pin_role']} ({lib_pin.kind})",
                ))
                continue
            options = buses_by_type.get(wanted, [])
            if not options:
                unresolved.append(SolverWarning(
                    level="warn", code="no_matching_bus",
                    text=(
                        f"{comp['id']}.{conn['pin_role']} needs a {wanted} bus "
                        "but the design has none. Add one with add_bus before solving."
                    ),
                ))
                continue
            choice_bus = options[0]
            old = dict(target)
            new = {"kind": "bus", "bus_id": choice_bus}
            conn["target"] = new
            assigned.append(PinAssignment(comp["id"], conn["pin_role"], old, new))

        elif kind == "expander_pin":
            if not expanders:
                unresolved.append(SolverWarning(
                    level="warn", code="no_expander",
                    text=(
                        f"{comp['id']}.{conn['pin_role']} targets an expander pin but "
                        "the design has no io_expander component"
                    ),
                ))
                continue
            chosen = _solve_expander_pin(expanders, expander_pin_count, used_expander_pins)
            if not chosen:
                unresolved.append(SolverWarning(
                    level="warn", code="no_expander_pin",
                    text=f"no free expander pin available for {comp['id']}.{conn['pin_role']}",
                ))
                continue
            ex_id, number = chosen
            old = dict(target)
            new = {**target, "expander_id": ex_id, "number": number}
            conn["target"] = new
            used_expander_pins.add(chosen)
            assigned.append(PinAssignment(comp["id"], conn["pin_role"], old, new))

    warnings = list(_static_warnings(design, board, library_components))
    return SolveResult(design=design, assigned=assigned, unresolved=unresolved, warnings=warnings)


def _solve_gpio(board: LibraryBoard, lib_pin: Pin, used: set[str]) -> Optional[str]:
    for candidate in _gpio_candidates_for_pin(board, lib_pin):
        if candidate not in used:
            return candidate
    return None


def _apply_locked_pins(
    design: dict,
    components_by_id: dict[str, dict],
    library_components: dict[str, "LibraryComponent"],
    used_gpios: set[str],
    assigned: list[PinAssignment],
) -> list[SolverWarning]:
    """Walk every connection and reconcile it against its component's
    `locked_pins` map (role -> board pin). Mutates ``design`` (in place
    via the connection dict) and ``used_gpios``/``assigned``. Returns
    any warnings produced."""
    warnings: list[SolverWarning] = []

    # First pass: surface lock entries that don't correspond to any role
    # the library component declares. The connection loop below would skip
    # these silently because nothing matches `conn.pin_role == role`.
    for cid, comp in components_by_id.items():
        locked = comp.get("locked_pins") or {}
        if not isinstance(locked, dict):
            continue
        lib_comp = library_components.get(cid)
        if lib_comp is None:
            continue
        valid_roles = {p.role for p in lib_comp.electrical.pins}
        for role, locked_pin in locked.items():
            if role not in valid_roles:
                warnings.append(SolverWarning(
                    level="warn", code="locked_pin_unknown_role",
                    text=(
                        f"{cid}.{role} is locked to '{locked_pin}' but the "
                        f"role does not exist on library component "
                        f"'{comp.get('library_id')}'."
                    ),
                ))

    for conn in design.get("connections", []):
        comp = components_by_id.get(conn.get("component_id"))
        if not comp:
            continue
        locked = comp.get("locked_pins") or {}
        if not isinstance(locked, dict) or not locked:
            continue
        role = conn.get("pin_role")
        if role not in locked:
            continue
        locked_pin = str(locked[role])

        # The lock is meaningless when the connection isn't a gpio target.
        # We surface this so authors don't expect the solver to honour it.
        target = conn.get("target") or {}
        if target.get("kind") != "gpio":
            warnings.append(SolverWarning(
                level="warn", code="locked_pin_wrong_kind",
                text=(
                    f"{comp['id']}.{role} has locked_pins='{locked_pin}' but its "
                    f"connection target is kind='{target.get('kind')}', not gpio. "
                    f"The lock is being ignored."
                ),
            ))
            continue

        # The unknown-role check ran in the first pass above. compatibility.py
        # handles the deeper capability check (locked pin lacks required caps).
        existing = target.get("pin") or ""
        if existing == locked_pin:
            # Already aligned with the lock; ensure it's reserved so the
            # downstream solver doesn't try to hand the same pin to a
            # different unbound connection.
            used_gpios.add(locked_pin)
            continue

        if existing and existing != locked_pin:
            warnings.append(SolverWarning(
                level="warn", code="locked_pin_mismatch",
                text=(
                    f"{comp['id']}.{role} is bound to '{existing}' but locked_pins "
                    f"says '{locked_pin}'. Update the lock or the connection so "
                    f"they agree."
                ),
            ))
            # Don't auto-rewrite a bound pin -- the divergence might be
            # intentional and the user needs to decide. Just reserve the
            # locked pin to keep the rest of the solver out of conflict.
            used_gpios.add(locked_pin)
            continue

        # Empty/unbound target -> apply the lock as the assignment.
        old = dict(target)
        new = {"kind": "gpio", "pin": locked_pin}
        conn["target"] = new
        used_gpios.add(locked_pin)
        assigned.append(PinAssignment(comp["id"], role, old, new))
    return warnings


def _bus_type_for_pin(kind: str) -> Optional[str]:
    if kind in ("i2c_sda", "i2c_scl"):
        return "i2c"
    if kind in ("spi_clk", "spi_miso", "spi_mosi"):
        return "spi"
    if kind in ("i2s_lrclk", "i2s_bclk"):
        return "i2s"
    if kind in ("uart_rx", "uart_tx"):
        return "uart"
    return None


def _expander_size_for(cid: str, library_components: dict[str, LibraryComponent]) -> int:
    name = library_components[cid].id.lower()
    if "23017" in name:
        return 16
    if "23008" in name:
        return 8
    return 8


def _solve_expander_pin(
    expanders: dict[str, LibraryComponent],
    pin_counts: dict[str, int],
    used: set[tuple[str, int]],
) -> Optional[tuple[str, int]]:
    for ex_id in expanders:
        size = pin_counts.get(ex_id, 8)
        for n in range(size):
            if (ex_id, n) not in used:
                return (ex_id, n)
    return None


def _static_warnings(
    design: dict, board: LibraryBoard,
    library_components: dict[str, LibraryComponent],
) -> list[SolverWarning]:
    out: list[SolverWarning] = []

    # Conflict detection on bound GPIO pins.
    pin_users: dict[str, list[str]] = defaultdict(list)
    for c in design.get("connections", []):
        t = c.get("target") or {}
        if t.get("kind") == "gpio" and t.get("pin"):
            pin_users[t["pin"]].append(f"{c['component_id']}.{c['pin_role']}")
    for pin, users in pin_users.items():
        if len(users) > 1:
            out.append(SolverWarning(
                level="warn", code="gpio_conflict",
                text=f"{pin} is targeted by multiple connections: {', '.join(users)}",
            ))

    # Conflict on expander pins.
    expander_users: dict[tuple[str, int], list[str]] = defaultdict(list)
    for c in design.get("connections", []):
        t = c.get("target") or {}
        if t.get("kind") == "expander_pin" and t.get("expander_id") and t.get("number") is not None:
            expander_users[(t["expander_id"], int(t["number"]))].append(f"{c['component_id']}.{c['pin_role']}")
    for (ex, n), users in expander_users.items():
        if len(users) > 1:
            out.append(SolverWarning(
                level="warn", code="expander_pin_conflict",
                text=f"expander {ex} pin {n} is targeted by: {', '.join(users)}",
            ))

    # Current budget.
    budget = (design.get("power") or {}).get("budget_ma")
    if budget:
        peak = sum(
            (lib.electrical.current_ma_peak or 0)
            for lib in library_components.values()
        )
        if peak > budget:
            out.append(SolverWarning(
                level="warn", code="current_budget",
                text=f"estimated peak {int(peak)}mA exceeds power.budget_ma {budget}mA",
            ))

    return out
