"""Intent-to-device synthesis (phase 1): library capability annotations,
automation schema in design.json, generator lowering, validator warnings."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wirestudio.generate.yaml_gen import _lower_automations, render_yaml
from wirestudio.intent import validate_automations
from wirestudio.library import default_library
from wirestudio.model import Automation, AutomationAction, AutomationTrigger, Design


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = REPO_ROOT / "wirestudio" / "examples" / "button-toggles-light.json"


@pytest.fixture
def lib():
    return default_library()


@pytest.fixture
def example(lib) -> Design:
    return Design.model_validate(json.loads(EXAMPLE.read_text()))


def _design(automations: list[dict]) -> Design:
    return Design.model_validate({
        "schema_version": "0.1",
        "id": "t", "name": "T",
        "board": {"library_id": "wemos-d1-mini", "mcu": "esp8266", "framework": "arduino"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": [
            {"id": "btn", "library_id": "gpio_input",  "label": "Button"},
            {"id": "lt",  "library_id": "gpio_output", "label": "Light"},
        ],
        "connections": [
            {"component_id": "btn", "pin_role": "IN",  "target": {"kind": "gpio", "pin": "D5"}},
            {"component_id": "lt",  "pin_role": "OUT", "target": {"kind": "gpio", "pin": "D6"}},
        ],
        "automations": automations,
    })


# --- schema --------------------------------------------------------------

def test_gpio_input_carries_a_capability_block(lib):
    cap = lib.component("gpio_input").capability
    assert cap is not None
    assert cap.role == "input"
    assert {p.event for p in cap.provides} == {"on_press", "on_release", "on_click", "on_state"}
    assert cap.accepts == []  # an input has no actions


def test_gpio_output_carries_actions_with_explicit_esphome_verbs(lib):
    cap = lib.component("gpio_output").capability
    assert cap is not None
    assert cap.role == "output"
    by_action = {a.action: a.esphome for a in cap.accepts}
    assert by_action == {
        "turn_on":  "switch.turn_on",
        "turn_off": "switch.turn_off",
        "toggle":   "switch.toggle",
    }


def test_unannotated_components_keep_capability_none(lib):
    # The annotation rollout is incremental; an un-annotated component still
    # loads, it just can't participate in `automations` yet.
    assert lib.component("hc-sr501").capability is None


def test_automation_round_trips_through_the_model():
    d = _design([{
        "id": "a1",
        "trigger": {"component_id": "btn", "event": "on_press"},
        "actions": [{"component_id": "lt", "action": "toggle"}],
    }])
    assert len(d.automations) == 1
    a = d.automations[0]
    assert isinstance(a, Automation)
    assert isinstance(a.trigger, AutomationTrigger)
    assert isinstance(a.actions[0], AutomationAction)
    assert a.trigger.event == "on_press"


# --- lowering ------------------------------------------------------------

def test_lowering_emits_short_form_when_no_args(lib):
    d = _design([{
        "id": "a1",
        "trigger": {"component_id": "btn", "event": "on_press"},
        "actions": [{"component_id": "lt", "action": "toggle"}],
    }])
    out = _lower_automations(d, lib)
    assert out == {"btn": {"on_press": [{"switch.toggle": "lt"}]}}


def test_lowering_emits_long_form_when_args_present(lib):
    # gpio_output's accept verbs don't take args today, but the lowering
    # shape must handle the general case (light.turn_on with brightness etc.)
    # so the path is exercised here against the gpio_output adapter.
    d = _design([{
        "id": "a1",
        "trigger": {"component_id": "btn", "event": "on_press"},
        "actions": [{"component_id": "lt", "action": "turn_on", "args": {"transition_length": "1s"}}],
    }])
    out = _lower_automations(d, lib)
    assert out == {"btn": {"on_press": [
        {"switch.turn_on": {"id": "lt", "transition_length": "1s"}},
    ]}}


def test_lowering_extends_a_user_authored_param_list(lib):
    # If a user already set params.on_press to a raw action list (the
    # escape hatch), the automation-graph entries extend that list rather
    # than silently replacing it -- nothing the user wrote is lost.
    d = _design([{
        "id": "a1",
        "trigger": {"component_id": "btn", "event": "on_press"},
        "actions": [{"component_id": "lt", "action": "toggle"}],
    }])
    btn = next(c for c in d.components if c.id == "btn")
    btn.params["on_press"] = [{"logger.log": "manual"}]
    yaml = render_yaml(d, lib)
    assert 'on_press' in yaml
    # Both the user-authored logger.log AND the lowered switch.toggle land.
    assert "logger.log: manual" in yaml
    assert "switch.toggle: porch_light" not in yaml  # different ids in this fixture
    assert "switch.toggle: lt" in yaml


def test_lowering_silently_drops_dangling_refs_in_yaml(lib):
    # The validator surfaces the warning; the renderer must not emit invalid
    # YAML referencing the missing id.
    d = _design([{
        "id": "a1",
        "trigger": {"component_id": "btn", "event": "on_press"},
        "actions": [{"component_id": "nope", "action": "toggle"}],
    }])
    yaml = render_yaml(d, lib)
    assert "nope" not in yaml          # no dangling ref in the output
    assert "on_press" not in yaml      # the trigger has no actions, so the key drops too


# --- generator end-to-end + golden ---------------------------------------

def test_button_toggles_light_example_matches_golden(example, lib):
    expected = (REPO_ROOT / "tests" / "golden" / "button-toggles-light.yaml").read_text()
    assert render_yaml(example, lib) == expected


def test_button_toggles_light_yaml_contains_the_lowered_automation(example, lib):
    yaml = render_yaml(example, lib)
    assert "on_press:\n  - switch.toggle: porch_light" in yaml


# --- validator -----------------------------------------------------------

def test_validator_quiet_on_a_well_formed_automation(example, lib):
    assert validate_automations(example, lib) == []


def test_validator_flags_unknown_trigger_component(lib):
    d = _design([{
        "id": "a1",
        "trigger": {"component_id": "missing", "event": "on_press"},
        "actions": [{"component_id": "lt", "action": "toggle"}],
    }])
    codes = [w.code for w in validate_automations(d, lib)]
    assert "automation_unknown_component" in codes


def test_validator_flags_unknown_event(lib):
    d = _design([{
        "id": "a1",
        "trigger": {"component_id": "btn", "event": "on_double_press"},  # not provided
        "actions": [{"component_id": "lt", "action": "toggle"}],
    }])
    warns = validate_automations(d, lib)
    assert any(w.code == "automation_unknown_event" for w in warns)
    assert any("on_press" in w.text for w in warns)  # lists what IS provided


def test_validator_flags_unknown_action(lib):
    d = _design([{
        "id": "a1",
        "trigger": {"component_id": "btn", "event": "on_press"},
        "actions": [{"component_id": "lt", "action": "set_brightness"}],  # not accepted
    }])
    codes = [w.code for w in validate_automations(d, lib)]
    assert "automation_unknown_action" in codes


def test_validator_flags_component_without_capability(lib):
    # hc-sr501 has no capability block, so it can't be used as a trigger
    # source even though it's a real component in the library.
    d = Design.model_validate({
        "schema_version": "0.1", "id": "t", "name": "T",
        "board": {"library_id": "wemos-d1-mini", "mcu": "esp8266", "framework": "arduino"},
        "power": {"supply": "usb", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": [
            {"id": "pir", "library_id": "hc-sr501", "label": "PIR"},
            {"id": "lt",  "library_id": "gpio_output", "label": "Light"},
        ],
        "automations": [{
            "id": "a1",
            "trigger": {"component_id": "pir", "event": "on_state"},
            "actions": [{"component_id": "lt", "action": "turn_on"}],
        }],
    })
    codes = [w.code for w in validate_automations(d, lib)]
    assert "automation_component_no_capability" in codes
