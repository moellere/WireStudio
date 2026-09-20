"""Rule-based electrical checks a block declares about itself.

No simulation: each check is one line of arithmetic over the block's
stated assumptions and the instance's params, and the report prints the
numbers it used. What a block does not declare stays uncovered and the
report says so.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Optional

from wirestudio.inventory.match import normalize_value
from wirestudio.library import ElectricalCheck, LibraryComponent, PinRef, part_value

PinVoltage = Callable[[str], Optional[float]]


@dataclass
class CheckResult:
    kind: str
    ok: bool
    text: str


class Unresolved(Exception):
    """A check could not be evaluated here (a rail voltage only a design
    knows, a param nobody set); the caller reports it, not a verdict."""


def run_checks(
    component: LibraryComponent,
    params: Mapping[str, object],
    pin_voltage: PinVoltage,
) -> tuple[list[CheckResult], list[str]]:
    """(results, unresolved) for every declared check, with `params`
    over the schema defaults and `pin_voltage(role)` supplying what a
    `{pin: ROLE}` reference means in this context."""
    if component.verify is None:
        return [], []
    merged = {
        key: spec["default"] for key, spec in component.params_schema.items()
        if isinstance(spec, dict) and "default" in spec
    }
    merged.update(params)
    results: list[CheckResult] = []
    unresolved: list[str] = []
    for check in component.verify.checks:
        try:
            results.append(_RUNNERS[check.kind](component, check, merged, pin_voltage))
        except Unresolved as e:
            unresolved.append(f"{check.kind}: {e}")
    return results, unresolved


def _volts(ref: float | PinRef, pin_voltage: PinVoltage) -> float:
    if isinstance(ref, PinRef):
        v = pin_voltage(ref.pin)
        if v is None:
            raise Unresolved(f"voltage on {ref.pin} is not known here")
        return v
    return float(ref)


def _amount(ref: float | str, params: Mapping[str, object], what: str) -> float:
    if isinstance(ref, str):
        raw = params.get(ref)
        if raw is None:
            raise Unresolved(f"{what} comes from param {ref!r}, which is not set")
        try:
            return float(raw)
        except (TypeError, ValueError) as e:
            raise Unresolved(f"param {ref!r} is not a number: {raw!r}") from e
    return float(ref)


def _ohms(component: LibraryComponent, part_id: str, params: Mapping[str, object]) -> tuple[str, float]:
    part = next((p for p in (component.subcircuit.parts if component.subcircuit else []) if p.id == part_id), None)
    if part is None:
        raise Unresolved(f"no subcircuit part {part_id!r}")
    printed = part_value(part, params, component.params_schema)
    ohms = normalize_value(printed, "resistor")
    if ohms is None or ohms <= 0:
        raise Unresolved(f"{part_id} value {printed!r} is not a resistance")
    return printed, ohms


def _led_current(component, check: ElectricalCheck, params, pin_voltage) -> CheckResult:
    printed, r = _ohms(component, check.resistor, params)
    v = _volts(check.drive, pin_voltage)
    ma = max(v - check.vf_v, 0.0) / r * 1000
    ok = check.min_ma <= ma <= check.max_ma
    return CheckResult("led_current", ok, (
        f"LED current {ma:.1f} mA through {check.resistor} {printed} at {v:g} V "
        f"(Vf {check.vf_v:g} V): {'within' if ok else 'outside'} {check.min_ma:g}-{check.max_ma:g} mA"))


def _base_drive(component, check: ElectricalCheck, params, pin_voltage) -> CheckResult:
    printed, r = _ohms(component, check.resistor, params)
    v = _volts(check.drive, pin_voltage)
    ib_ma = max(v - check.vbe_v, 0.0) / r * 1000
    sat_ma = ib_ma * check.hfe_min
    load_ma = _amount(check.load, params, "load current")
    ok = load_ma <= sat_ma and load_ma <= check.max_ma
    why = (
        "saturates" if ok else
        f"exceeds the {check.max_ma:g} mA rating" if load_ma > check.max_ma else
        f"exceeds what {ib_ma:.2f} mA of base current saturates ({sat_ma:.0f} mA at hFE {check.hfe_min:g})"
    )
    return CheckResult("base_drive", ok, (
        f"base drive {ib_ma:.2f} mA through {check.resistor} {printed} at {v:g} V saturates up to "
        f"{sat_ma:.0f} mA (hFE >= {check.hfe_min:g}); load {load_ma:g} mA {why}"))


def _gate_drive(component, check: ElectricalCheck, params, pin_voltage) -> CheckResult:
    v = _volts(check.drive, pin_voltage)
    load_ma = _amount(check.load, params, "load current")
    watts = (load_ma / 1000) ** 2 * check.rds_on_ohm
    enhanced = v >= check.vgs_on_v
    cool = watts <= check.max_w
    ok = enhanced and cool and (check.max_ma is None or load_ma <= check.max_ma)
    bits = [f"gate at {v:g} V {'reaches' if enhanced else 'is below'} the {check.vgs_on_v:g} V the FET needs to be fully on"]
    bits.append(f"{load_ma:g} mA through {check.rds_on_ohm:g} ohm dissipates {watts:.2f} W "
                f"({'within' if cool else 'over'} {check.max_w:g} W without a heatsink)")
    if check.max_ma is not None and load_ma > check.max_ma:
        bits.append(f"load exceeds the {check.max_ma:g} mA rating")
    return CheckResult("gate_drive", ok, "; ".join(bits))


def _divider(component, check: ElectricalCheck, params, pin_voltage) -> CheckResult:
    top_printed, r_top = _ohms(component, check.r_top, params)
    bottom_printed, r_bottom = _ohms(component, check.r_bottom, params)
    sense_v = _amount(check.sense, params, "sensed voltage")
    pin_v = sense_v * r_bottom / (r_top + r_bottom)
    bleed_ua = sense_v / (r_top + r_bottom) * 1e6
    ok = pin_v <= check.max_pin_v
    return CheckResult("divider", ok, (
        f"{sense_v:g} V through {check.r_top} {top_printed} / {check.r_bottom} {bottom_printed} "
        f"puts {pin_v:.2f} V on the pin ({'within' if ok else 'over'} the {check.max_pin_v:g} V ceiling), "
        f"drawing {bleed_ua:.0f} uA"))


_RUNNERS = {
    "led_current": _led_current,
    "base_drive": _base_drive,
    "gate_drive": _gate_drive,
    "divider": _divider,
}
