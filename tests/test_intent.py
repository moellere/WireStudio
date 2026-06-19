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
    # loads, it just can't participate in `automations` yet. `mpu6050` is a
    # 7-channel IMU (accel x/y/z + gyro x/y/z + die temp) -- too rich to
    # enumerate as triggers without a further design call, so it stays
    # capability=None for now.
    assert lib.component("mpu6050").capability is None


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
    # mpu6050 is a 7-channel IMU (accel x/y/z + gyro x/y/z + die temp) -- too
    # rich to enumerate as triggers without further design, so it carries no
    # capability block today and can't be a trigger source.
    d = Design.model_validate({
        "schema_version": "0.1", "id": "t", "name": "T",
        "board": {"library_id": "wemos-d1-mini", "mcu": "esp8266", "framework": "arduino"},
        "power": {"supply": "usb", "rail_voltage_v": 5.0, "budget_ma": 500},
        "buses": [{"id": "i2c0", "type": "i2c", "sda": "D2", "scl": "D1"}],
        "components": [
            {"id": "imu", "library_id": "mpu6050", "label": "IMU"},
            {"id": "lt",  "library_id": "gpio_output", "label": "Light"},
        ],
        "connections": [
            {"component_id": "imu", "pin_role": "SDA", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "imu", "pin_role": "SCL", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "lt",  "pin_role": "OUT", "target": {"kind": "gpio", "pin": "D6"}},
        ],
        "automations": [{
            "id": "a1",
            "trigger": {"component_id": "imu", "event": "on_value"},
            "actions": [{"component_id": "lt", "action": "turn_on"}],
        }],
    })
    codes = [w.code for w in validate_automations(d, lib)]
    assert "automation_component_no_capability" in codes


# --- phase 1.5a: capability annotations on the broader library --------------
#
# 10 components gain capability blocks. The annotation must be congruent with
# the existing ESPHome template -- a `provides` entry whose key the template
# doesn't pass through is silently broken (the automation lowers into a
# `params.<key>` the template ignores), so each provides is verified against
# the actual template, and each accepts has an explicit ESPHome verb.

# (component_id, role, provides, accepts) — sourced from each component's
# template passthroughs + ESPHome's documented action verbs.
_PHASE_1_5_ANNOTATIONS = [
    ("hc-sr501",        "input",  ["on_press", "on_release"],                                []),
    ("rcwl-0516",       "input",  ["on_press", "on_release"],                                []),
    ("rc522",           "input",  ["on_tag", "on_tag_removed"],                              []),
    ("rdm6300",         "input",  ["on_tag"],                                                []),
    ("rotary_encoder",  "input",  ["on_clockwise", "on_anticlockwise", "on_value"],          []),
    ("adc",             "sensor", ["on_value", "on_value_range"],                            []),
    ("hc-sr04",         "sensor", ["on_value"],                                              []),
    ("rf_bridge",       "input",  ["on_code_received"],                                      []),
    ("ws2812b",         "output", ["on_turn_on", "on_turn_off"],                             ["turn_on", "turn_off", "toggle"]),
    ("tuya_switch",     "output", [],                                                        ["turn_on", "turn_off", "toggle"]),
]

# --- phase 1.5b: single-output sensors gain on_value triggers ----------------
#
# The remaining single-value sensors get a params.on_value / on_value_range
# passthrough plus a role=sensor capability, so a sensor reading can drive an
# automation. Multi-channel sensors (dht, bme280, IMUs, power meters) are
# deferred: which sub-channel a trigger hangs off is a separate design call.
_PHASE_1_5B_ANNOTATIONS = [
    ("ds18b20",         "sensor", ["on_value", "on_value_range"], []),
    ("bh1750",          "sensor", ["on_value", "on_value_range"], []),
    ("tsl2561",         "sensor", ["on_value", "on_value_range"], []),
    ("vl53l0x",         "sensor", ["on_value", "on_value_range"], []),
    ("hx711",           "sensor", ["on_value", "on_value_range"], []),
    ("max31855",        "sensor", ["on_value", "on_value_range"], []),
    ("pulse_counter",   "sensor", ["on_value", "on_value_range"], []),
    ("ads1115_channel", "sensor", ["on_value", "on_value_range"], []),
    ("tuya_sensor",     "sensor", ["on_value", "on_value_range"], []),
]

# --- phase 2: value -> transform -> action -----------------------------------
#
# A sensor/encoder value drives an action through a transform the generator
# lowers to a `!lambda`. The encoder gains on_value (above); the stepper is the
# action target (accepts set_target -> stepper.set_target, no passthrough since
# the action references the stepper by id).
_PHASE_2_ANNOTATIONS = [
    ("uln2003", "output", [], ["set_target"]),
]

# --- phase 3: multi-channel sensor triggers ---------------------------------
#
# A trigger on a multi-channel sensor (e.g. bme280) carries a `channel:`
# selector matching the sub-block the on_value belongs to. The capability
# provides list one entry per channel. The lowering combines channel + event
# into a `<channel>_<event>` params key, so the template's per-channel
# `params.temperature_on_value` (etc.) passthrough fires inside the right
# sub-block.
#
# (component_id, role, [(channel, event), ...])
_PHASE_3_MULTICHANNEL = [
    ("dht",     "sensor", [("temperature", "on_value"), ("humidity", "on_value")]),
    ("bme280",  "sensor", [("temperature", "on_value"), ("humidity", "on_value"),
                           ("pressure", "on_value")]),
    ("bmp180",  "sensor", [("temperature", "on_value"), ("pressure", "on_value")]),
    ("bmp280",  "sensor", [("temperature", "on_value"), ("pressure", "on_value")]),
    ("aht10",   "sensor", [("temperature", "on_value"), ("humidity", "on_value")]),
    ("htu21d",  "sensor", [("temperature", "on_value"), ("humidity", "on_value")]),
    ("sht3xd",  "sensor", [("temperature", "on_value"), ("humidity", "on_value")]),
]

_ALL_ANNOTATIONS = _PHASE_1_5_ANNOTATIONS + _PHASE_1_5B_ANNOTATIONS + _PHASE_2_ANNOTATIONS


@pytest.mark.parametrize("lib_id, role, provides, accepts", _ALL_ANNOTATIONS)
def test_phase_1_5_capability_annotation_shape(lib, lib_id, role, provides, accepts):
    cap = lib.component(lib_id).capability
    assert cap is not None, f"{lib_id} should have a capability block"
    assert cap.role == role
    assert [p.event for p in cap.provides] == provides
    assert [a.action for a in cap.accepts] == accepts


def test_phase_1_5_provides_only_keys_the_template_passes_through(lib):
    """Each annotated `provides.event` must match a `params.<event>`
    passthrough in the component's own ESPHome template; otherwise the
    automation lowers into a key the renderer drops on the floor."""
    import re
    for lib_id, _role, provides, _accepts in _ALL_ANNOTATIONS:
        tmpl = lib.component(lib_id).esphome.yaml_template or ""
        passthroughs = set(re.findall(r"params\.(on_\w+)", tmpl))
        for ev in provides:
            assert ev in passthroughs, (
                f"{lib_id}: capability declares provides.event={ev!r} but the "
                f"template has no params.{ev} passthrough -- the automation "
                f"would lower into a key the renderer drops. Template passes "
                f"through: {sorted(passthroughs) or '(none)'}"
            )


def test_phase_1_5_accepts_have_known_esphome_verb_prefixes(lib):
    """`accepts.esphome` must be a `<platform>.<verb>` action ESPHome
    recognises. The platform prefix is asserted against the small set of
    platforms phase 1.5 covers (switch / light / stepper). Catches typos."""
    known_prefixes = {"switch", "light", "stepper"}
    for lib_id, _role, _provides, accepts in _ALL_ANNOTATIONS:
        cap = lib.component(lib_id).capability
        if not cap or not cap.accepts:
            continue
        for acc, declared in zip(accepts, cap.accepts):
            assert declared.action == acc
            prefix, _, _ = declared.esphome.partition(".")
            assert prefix in known_prefixes, (
                f"{lib_id} accepts.{acc} -> {declared.esphome!r}: "
                f"unknown ESPHome platform prefix {prefix!r}"
            )


# --- second worked example: motion -> light --------------------------------

MOTION_EXAMPLE = REPO_ROOT / "wirestudio" / "examples" / "motion-turns-on-light.json"


def test_motion_to_light_example_matches_golden(lib):
    d = Design.model_validate(json.loads(MOTION_EXAMPLE.read_text()))
    expected = (REPO_ROOT / "tests" / "golden" / "motion-turns-on-light.yaml").read_text()
    assert render_yaml(d, lib) == expected


def test_motion_to_light_lowers_both_events_to_light_actions(lib):
    """Both edges of motion fire a light action through the same lowering."""
    d = Design.model_validate(json.loads(MOTION_EXAMPLE.read_text()))
    yaml = render_yaml(d, lib)
    assert "on_press:\n  - light.turn_on: porch_light" in yaml
    assert "on_release:\n  - light.turn_off: porch_light" in yaml


def test_motion_to_light_validator_quiet(lib):
    d = Design.model_validate(json.loads(MOTION_EXAMPLE.read_text()))
    assert validate_automations(d, lib) == []


# --- phase 1.5b: a sensor value drives an action ---------------------------

def test_sensor_on_value_lowers_into_the_sensor_template(lib):
    """A single-output sensor's on_value trigger lowers a switch action into the
    rendered sensor block -- the 1.5b path that lets a reading drive an automation."""
    d = Design.model_validate({
        "schema_version": "0.1", "id": "t", "name": "T",
        "board": {"library_id": "wemos-d1-mini", "mcu": "esp8266", "framework": "arduino"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "buses": [{"id": "wire0", "type": "1wire", "pin": "D4"}],
        "components": [
            {"id": "temp", "library_id": "ds18b20", "label": "Temp",
             "params": {"address": "0x1234567890abcdef"}},
            {"id": "fan",  "library_id": "gpio_output", "label": "Fan"},
        ],
        "connections": [
            {"component_id": "temp", "pin_role": "DATA", "target": {"kind": "bus", "bus_id": "wire0"}},
            {"component_id": "fan",  "pin_role": "OUT",  "target": {"kind": "gpio", "pin": "D6"}},
        ],
        "automations": [{
            "id": "a1",
            "trigger": {"component_id": "temp", "event": "on_value"},
            "actions": [{"component_id": "fan", "action": "turn_on"}],
        }],
    })
    assert validate_automations(d, lib) == []
    assert "on_value:\n  - switch.turn_on: fan" in render_yaml(d, lib)


# --- phase 3: multi-channel sensor capability + lowering ---------------------

@pytest.mark.parametrize("lib_id, role, channels", _PHASE_3_MULTICHANNEL)
def test_phase_3_multichannel_capability_shape(lib, lib_id, role, channels):
    cap = lib.component(lib_id).capability
    assert cap is not None and cap.role == role
    actual = [(p.channel, p.event) for p in cap.provides]
    assert actual == channels
    # Every entry is a value-kind provide
    assert all(p.kind == "value" for p in cap.provides)


def test_phase_3_provides_match_template_per_channel_passthroughs(lib):
    """Each (channel, event) pair must match a `params.<channel>_<event>`
    passthrough in the component's template, INSIDE the matching sub-block."""
    import re
    for lib_id, _role, channels in _PHASE_3_MULTICHANNEL:
        tmpl = lib.component(lib_id).esphome.yaml_template or ""
        passthroughs = set(re.findall(r"params\.([a-z]+_on_\w+)", tmpl))
        for channel, event in channels:
            key = f"{channel}_{event}"
            assert key in passthroughs, (
                f"{lib_id}: capability declares ({channel!r}, {event!r}) but the "
                f"template has no params.{key} passthrough. Template has: "
                f"{sorted(passthroughs) or '(none)'}"
            )


TEMP_FAN_EXAMPLE = REPO_ROOT / "wirestudio" / "examples" / "temp-turns-on-fan.json"


def test_temp_to_fan_example_matches_golden(lib):
    d = Design.model_validate(json.loads(TEMP_FAN_EXAMPLE.read_text()))
    expected = (REPO_ROOT / "tests" / "golden" / "temp-turns-on-fan.yaml").read_text()
    assert render_yaml(d, lib) == expected


def test_temp_to_fan_lowers_into_the_temperature_sub_block(lib):
    """The bme280's temperature channel trigger lands on_value inside the
    temperature sub-block -- not at the platform level, not under humidity."""
    d = Design.model_validate(json.loads(TEMP_FAN_EXAMPLE.read_text()))
    yaml = render_yaml(d, lib)
    # Asserts both the sub-block placement and the absence of stray on_value
    # on the sibling humidity/pressure channels.
    expected = (
        "  temperature:\n"
        "    name: Climate Temperature\n"
        "    on_value:\n"
        "    - switch.turn_on: fan\n"
        "  humidity:\n"
        "    name: Climate Humidity\n"
        "  pressure:\n"
        "    name: Climate Pressure"
    )
    assert expected in yaml


def test_temp_to_fan_validator_quiet(lib):
    d = Design.model_validate(json.loads(TEMP_FAN_EXAMPLE.read_text()))
    assert validate_automations(d, lib) == []


def test_validator_flags_unknown_channel_on_multichannel_sensor(lib):
    """A trigger naming a channel the component doesn't provide surfaces
    automation_unknown_event, and the warning text lists what IS provided as
    `<channel>.<event>` pairs so the fix is obvious."""
    d = Design.model_validate({
        "schema_version": "0.1", "id": "t", "name": "T",
        "board": {"library_id": "wemos-d1-mini", "mcu": "esp8266", "framework": "arduino"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "buses": [{"id": "i2c0", "type": "i2c", "sda": "D2", "scl": "D1"}],
        "components": [
            {"id": "bme", "library_id": "bme280", "label": "Climate"},
            {"id": "fan", "library_id": "gpio_output", "label": "Fan"},
        ],
        "connections": [
            {"component_id": "bme", "pin_role": "SDA", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "bme", "pin_role": "SCL", "target": {"kind": "bus", "bus_id": "i2c0"}},
            {"component_id": "fan", "pin_role": "OUT", "target": {"kind": "gpio", "pin": "D6"}},
        ],
        "automations": [{
            "id": "a1",
            "trigger": {"component_id": "bme", "channel": "altitude", "event": "on_value"},
            "actions": [{"component_id": "fan", "action": "turn_on"}],
        }],
    })
    warns = validate_automations(d, lib)
    codes = [w.code for w in warns]
    assert "automation_unknown_event" in codes
    text = next(w.text for w in warns if w.code == "automation_unknown_event")
    assert "channel 'altitude'" in text
    assert "temperature.on_value" in text  # the warning lists what IS provided


# --- phase 2: value -> transform -> action (encoder -> stepper) -------------

ENCODER_EXAMPLE = REPO_ROOT / "wirestudio" / "examples" / "encoder-drives-stepper.json"


def test_encoder_drives_stepper_example_matches_golden(lib):
    d = Design.model_validate(json.loads(ENCODER_EXAMPLE.read_text()))
    expected = (REPO_ROOT / "tests" / "golden" / "encoder-drives-stepper.yaml").read_text()
    assert render_yaml(d, lib) == expected


def test_encoder_drives_stepper_validator_quiet(lib):
    d = Design.model_validate(json.loads(ENCODER_EXAMPLE.read_text()))
    assert validate_automations(d, lib) == []


def test_transform_lowers_to_a_lambda(lib):
    """A transform on an action lowers to `<arg>: !lambda "return <expr>;"` --
    the value→transform→action path. The expr rides through the tojson
    passthrough as a sentinel and is restored to a tagged !lambda scalar."""
    d = Design.model_validate(json.loads(ENCODER_EXAMPLE.read_text()))
    yaml = render_yaml(d, lib)
    assert "on_value:\n  - stepper.set_target:\n      id: motor\n      target: !lambda return (long) (x * 10);" in yaml


def test_transform_keeps_quotes_when_expr_is_not_plain_scalar_safe(lib):
    """An expression containing `: ` (e.g. a ternary) must stay quoted after the
    !lambda tag, or the emitted YAML would parse as a mapping."""
    d = Design.model_validate({
        "schema_version": "0.1", "id": "t", "name": "T",
        "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32", "framework": "arduino"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": [
            {"id": "knob",  "library_id": "rotary_encoder", "label": "Knob"},
            {"id": "motor", "library_id": "uln2003", "label": "Motor"},
        ],
        "connections": [
            {"component_id": "knob",  "pin_role": "A",   "target": {"kind": "gpio", "pin": "GPIO16"}},
            {"component_id": "knob",  "pin_role": "B",   "target": {"kind": "gpio", "pin": "GPIO17"}},
            {"component_id": "motor", "pin_role": "A",   "target": {"kind": "gpio", "pin": "GPIO25"}},
            {"component_id": "motor", "pin_role": "B",   "target": {"kind": "gpio", "pin": "GPIO26"}},
            {"component_id": "motor", "pin_role": "C",   "target": {"kind": "gpio", "pin": "GPIO27"}},
            {"component_id": "motor", "pin_role": "D",   "target": {"kind": "gpio", "pin": "GPIO14"}},
            {"component_id": "motor", "pin_role": "VCC", "target": {"kind": "rail", "rail": "5V"}},
            {"component_id": "motor", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
        ],
        "automations": [{
            "id": "a1",
            "trigger": {"component_id": "knob", "event": "on_value"},
            "actions": [{"component_id": "motor", "action": "set_target",
                         "transform": {"target": "x > 0 ? 100 : 0"}}],
        }],
    })
    yaml = render_yaml(d, lib)
    assert "target: !lambda 'return x > 0 ? 100 : 0;'" in yaml

