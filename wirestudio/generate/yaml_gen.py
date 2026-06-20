from __future__ import annotations

import re
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined, UndefinedError, select_autoescape

from wirestudio.library import Library
from wirestudio.model import Bus, Component, Design


class Secret(str):
    """String wrapper that dumps as a YAML `!secret <name>` tag."""


def _secret_representer(dumper: yaml.Dumper, data: Secret) -> yaml.ScalarNode:
    return dumper.represent_scalar("!secret", str(data), style="")


yaml.add_representer(Secret, _secret_representer)
yaml.SafeDumper.add_representer(Secret, _secret_representer)


class Lambda(str):
    """String wrapper that dumps as a YAML `!lambda <body>` tag -- an ESPHome
    inline lambda (e.g. `target: !lambda 'return (long) (x * 10);'`)."""


def _lambda_representer(dumper: yaml.Dumper, data: Lambda) -> yaml.ScalarNode:
    return dumper.represent_scalar("!lambda", str(data), style="'")


yaml.add_representer(Lambda, _lambda_representer)
yaml.SafeDumper.add_representer(Lambda, _lambda_representer)


# Lowered automation actions reach the renderer through the trigger template's
# `{{ params.on_* | tojson }}` passthrough, and JSON can't carry a YAML tag --
# a Lambda would flatten to a plain string. So carry it as a sentinel-prefixed
# string across the tojson -> safe_load round-trip, then restore it to a Lambda
# (which the final dump tags as `!lambda`) once the YAML is parsed back.
_LAMBDA_SENTINEL = "__wirestudio_lambda__:"


def _restore_lambdas(obj: Any) -> Any:
    if isinstance(obj, str):
        return Lambda(obj[len(_LAMBDA_SENTINEL):]) if obj.startswith(_LAMBDA_SENTINEL) else obj
    if isinstance(obj, list):
        return [_restore_lambdas(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _restore_lambdas(v) for k, v in obj.items()}
    return obj


def _str_representer(dumper: yaml.Dumper, data: str) -> yaml.ScalarNode:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(str, _str_representer)
yaml.SafeDumper.add_representer(str, _str_representer)


_jinja = Environment(
    undefined=StrictUndefined,
    keep_trailing_newline=False,
    autoescape=select_autoescape(default_for_string=False)
)
_jinja.policies["json.dumps_kwargs"] = {"sort_keys": False, "ensure_ascii": False}


def _bus_for(component_id: str, design: Design) -> Bus | None:
    for c in design.connections:
        if c.component_id == component_id and c.target.kind == "bus":
            for b in design.buses:
                if b.id == c.target.bus_id:
                    return b
    return None


def _parent_for(component_id: str, design: Design) -> dict[str, Any] | None:
    """Return the component-instance dict referenced by a kind:component
    connection on this component, or None if there is no such target.

    Used by hub-relative templates (e.g., ads1115_channel pointing at
    its ads1115 hub). The returned dict carries id + library_id +
    label + params so templates can read `{{ parent.id }}_hub` or
    `{{ parent.params.address }}` without re-walking the design.
    """
    for c in design.connections:
        if c.component_id == component_id and c.target.kind == "component":
            for inst in design.components:
                if inst.id == c.target.component_id:
                    return inst.model_dump()
    return None


def _pins_for(component_id: str, design: Design, library: Library) -> dict[str, Any]:
    """Return a dict of pin_role -> pin spec.

    For native GPIO connections, the value is the bare pin string (e.g. "GPIO13").
    For expander_pin connections, the value is the dict ESPHome expects under
    `pin:` -- discriminated by the expander's `esphome.expander_pin_key` if set
    (mcp23008/mcp23017 both use `mcp23xxx`), falling back to library_id otherwise.
    """
    pins: dict[str, Any] = {}
    by_id = {c.id: c for c in design.components}
    for c in design.connections:
        if c.component_id != component_id:
            continue
        t = c.target
        if t.kind == "gpio":
            pins[c.pin_role] = t.pin
        elif t.kind == "expander_pin":
            expander = by_id.get(t.expander_id)
            if expander is None:
                raise ValueError(
                    f"connection {component_id}.{c.pin_role} references unknown expander '{t.expander_id}'"
                )
            lib_expander = library.component(expander.library_id)
            key = lib_expander.esphome.expander_pin_key or expander.library_id
            block: dict[str, Any] = {key: t.expander_id, "number": t.number}
            if t.mode:
                block["mode"] = t.mode
            if t.inverted:
                block["inverted"] = t.inverted
            pins[c.pin_role] = block
    return pins


def _deep_merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if k in dst and isinstance(dst[k], list) and isinstance(v, list):
            dst[k].extend(v)
        elif k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def _lower_automations(design: Design, library: Library) -> dict[str, dict[str, list]]:
    """Lower `design.automations` into a `{component_id: {event_key: [actions]}}`
    map the renderer merges into the trigger component's `params`. Returns an
    empty map when a referenced component / event / action can't be resolved --
    the validator surfaces those as warnings; the renderer just drops the
    automation rather than emit invalid YAML.
    """
    by_id = {c.id: c for c in design.components}
    out: dict[str, dict[str, list]] = {}
    for auto in design.automations:
        trig_comp = by_id.get(auto.trigger.component_id)
        if trig_comp is None:
            continue
        try:
            trig_lib = library.component(trig_comp.library_id)
        except FileNotFoundError:
            continue
        cap = trig_lib.capability
        if cap is None:
            continue
        trig_channel = auto.trigger.channel
        provide = next(
            (p for p in cap.provides
             if p.event == auto.trigger.event and (p.channel or None) == (trig_channel or None)),
            None,
        )
        if provide is None:
            continue
        # When `esphome` is set, it's a full explicit override on the params key.
        # Otherwise build it from the channel + event so a multi-channel
        # template's per-channel passthrough (e.g. params.temperature_on_value)
        # fires inside the right sub-block.
        if provide.esphome:
            event_key = provide.esphome
        elif provide.channel:
            event_key = f"{provide.channel}_{provide.event}"
        else:
            event_key = provide.event

        action_list: list = []
        for act in auto.actions:
            act_comp = by_id.get(act.component_id)
            if act_comp is None:
                continue
            try:
                act_lib = library.component(act_comp.library_id)
            except FileNotFoundError:
                continue
            act_cap = act_lib.capability
            if act_cap is None:
                continue
            accept = next((a for a in act_cap.accepts if a.action == act.action), None)
            if accept is None:
                continue
            # Short form when there are no extra args: `{switch.toggle: porch_light}`.
            # Long form with args:                     `{light.turn_on: {id: porch_light, brightness: "50%"}}`.
            # Transform args lower to `!lambda "return <expr>;"` (phase 2,
            # value→transform→action): `{stepper.set_target: {id: motor, target: !lambda ...}}`.
            if act.args or act.transform:
                inner = {"id": act.component_id, **act.args}
                for arg_name, expr in act.transform.items():
                    inner[arg_name] = f"{_LAMBDA_SENTINEL}return {expr};"
                action_list.append({accept.esphome: inner})
            else:
                action_list.append({accept.esphome: act.component_id})

        if not action_list:
            continue
        # Condition gating: wrap the action list in `if: { condition, then }`
        # when one or more conditions resolve. A single condition emits as a
        # mapping under `condition:`; multiple emit as a list (ESPHome treats
        # the list form as implicit AND). Conditions that don't resolve
        # (unknown component / capability / predicate) are dropped silently;
        # the validator surfaces those as warnings.
        condition_items: list = []
        for cond in auto.conditions:
            cond_comp = by_id.get(cond.component_id)
            if cond_comp is None:
                continue
            try:
                cond_lib = library.component(cond_comp.library_id)
            except FileNotFoundError:
                continue
            cond_cap = cond_lib.capability
            if cond_cap is None:
                continue
            check = next((c for c in cond_cap.checks if c.predicate == cond.predicate), None)
            if check is None:
                continue
            condition_items.append({check.esphome: cond.component_id})
        if condition_items:
            condition_value: Any = (condition_items[0] if len(condition_items) == 1
                                    else condition_items)
            action_list = [{"if": {"condition": condition_value, "then": action_list}}]

        # on_value_range carries threshold bounds: ESPHome's syntax is a list
        # of {above, below, then} entries (vs. a flat action list for the other
        # triggers). Wrap the actions in a range entry when bounds are set so
        # the rendered YAML is `on_value_range: - above: 25.0\n    then: [...]`.
        if auto.trigger.above is not None or auto.trigger.below is not None:
            range_entry: dict[str, Any] = {}
            if auto.trigger.above is not None:
                range_entry["above"] = auto.trigger.above
            if auto.trigger.below is not None:
                range_entry["below"] = auto.trigger.below
            range_entry["then"] = action_list
            out.setdefault(trig_comp.id, {}).setdefault(event_key, []).append(range_entry)
        else:
            out.setdefault(trig_comp.id, {}).setdefault(event_key, []).extend(action_list)
    return out


def _render_component(
    comp: Component, design: Design, library: Library,
    auto_params: dict[str, dict[str, list]] | None = None,
) -> dict[str, Any]:
    lib_comp = library.component(comp.library_id)
    template_str = lib_comp.esphome.yaml_template
    if not template_str.strip():
        return {}
    bus = _bus_for(comp.id, design)
    parent = _parent_for(comp.id, design)
    # `board` carries the chip family / variant / mcu / framework so a
    # template can pick chip-specific platform names (e.g. rtttl uses
    # `ledc` on ESP32, `esp8266_pwm` on ESP8266). Templates that don't
    # need it ignore the key.
    try:
        board_lib = library.board(design.board.library_id)
        board_ctx = {
            "library_id": board_lib.id,
            "mcu": board_lib.mcu,
            "chip_variant": board_lib.chip_variant,
            "framework": board_lib.framework,
            "platformio_board": board_lib.platformio_board,
        }
    except FileNotFoundError:
        board_ctx = None
    # Merge lowered automations into params: each `params.on_*` list extends
    # any user-authored list rather than replacing it, so the existing escape
    # hatch (raw action YAML in `params.on_press`) still composes with new
    # automation-graph entries instead of silently losing either side.
    params = dict(comp.params)
    if auto_params:
        for key, actions in auto_params.get(comp.id, {}).items():
            existing = params.get(key)
            if isinstance(existing, list):
                params[key] = existing + actions
            elif existing is None:
                params[key] = actions
            else:
                # Existing param wasn't a list (single action dict); coerce.
                params[key] = [existing, *actions]
    ctx = {
        "id": comp.id,
        "label": comp.label,
        "params": params,
        "pins": _pins_for(comp.id, design, library),
        "bus": bus.model_dump() if bus else None,
        "parent": parent,
        "board": board_ctx,
    }
    try:
        rendered = _jinja.from_string(template_str).render(**ctx)
    except UndefinedError as e:
        # Two common shapes:
        #  - `bus.id` referenced but the component has no kind:bus connection
        #    (or the bus_id doesn't match any design.buses entry)
        #  - `params.<key>` referenced without an `is defined` guard for an
        #    optional param the user hasn't set
        # Tailor the hint to the message so we don't suggest a bus fix when
        # the actual error is a missing optional param.
        msg = e.message or ""
        # 'dict object' has no attribute 'x' -> the template walked into a
        # params dict that didn't have key 'x' (optional param without an
        # is-defined guard). 'None' has no attribute 'x' or any other shape
        # -> almost always a missing kind:bus connection (template referenced
        # bus.<...> and bus came back None).
        if "'dict object'" in msg:
            hint = (
                "Likely an optional param the template references without an "
                "`is defined` guard. Set the param under the component, or "
                "fix the template to guard the access."
            )
        else:
            hint = (
                "Likely a missing bus connection; add a matching bus to the "
                "design or fix the connection target."
            )
        raise ValueError(
            f"component '{comp.id}' (library_id={comp.library_id}) cannot be "
            f"rendered: {msg}. {hint}"
        ) from e
    except TypeError as e:
        # Jinja's StrictUndefined leaks past `tojson` because json.dumps gets
        # the StrictUndefined object as input and TypeErrors out before
        # Jinja's UndefinedError can fire (filters bypass the normal __call__
        # that triggers it). Most often: `{{ pins.OUT | tojson }}` against a
        # component whose OUT pin has no connection. Translate to a 422-able
        # ValueError with a hint at the likely cause.
        if "is not JSON serializable" in str(e):
            raise ValueError(
                f"component '{comp.id}' (library_id={comp.library_id}) cannot be rendered: "
                f"a referenced pin or bus has no connection. Add the missing connection "
                f"(or run solve_pins) and try again. Underlying error: {e}"
            ) from e
        raise
    parsed = yaml.safe_load(rendered)
    return _restore_lambdas(parsed) if parsed else {}


def _hz_to_freq(hz: int) -> str:
    if hz % 1_000_000 == 0:
        return f"{hz // 1_000_000}MHz"
    if hz % 1000 == 0:
        return f"{hz // 1000}kHz"
    return f"{hz}Hz"


def _secret_name(ref: str) -> str:
    return ref.removeprefix("!secret ").strip()


# Pinned ref for the lorawan-for-esphome external component. ESPHome's
# external_components: format embeds the ref in the source URL fragment
# (`github://owner/repo@<ref>`) rather than as a separate `ref:` key. Bumps
# are reviewed changes like any other dependency pin; switch to a tag after
# the component repo cuts its first stable release post hardware-join
# validation (decision logged in docs/lorawan/workflow-integration.md).
_LORAWAN_FOR_ESPHOME_REPO = "moellere/lorawan-for-esphome"
_LORAWAN_FOR_ESPHOME_REF = "main"  # TODO(lorawan): pin to a commit SHA after the join test runs


def _emit_lorawan_blocks(
    out: dict[str, Any],
    design: Design,
    library: Library,
    lorawan_secrets: dict[str, str] | None = None,
) -> None:
    """Emit the ESPHome external-component path for `lorawan-for-esphome`:
    `external_components:`, the `lorawan:` block (radio config from the board
    library, keys via !secret), and one `sensor: - platform: lorawan` binding
    per `design.lorawan.payload` entry. No-op unless `design.lorawan.payload`
    is non-empty -- the standalone Arduino path (target="lorawan") is rendered
    elsewhere and unaffected.

    `lorawan_secrets` is an optional mapping with the three literal keys
    (`dev_eui` / `join_eui` / `app_key`); when present, each key replaces the
    matching `!secret <name>` reference with a literal string in the rendered
    YAML. Used by the fleet push path so the rendered config carries the keys
    the provisioning step minted, without requiring a separate write to the
    fleet's secrets.yaml. Falls back to `!secret <name>` references for any
    key not in the override -- the dev-loop / `esphome config` gate keeps
    working.
    """
    lw = design.lorawan
    if lw is None or not lw.payload:
        return

    out.setdefault("external_components", []).append({
        "source": f"github://{_LORAWAN_FOR_ESPHOME_REPO}@{_LORAWAN_FOR_ESPHOME_REF}",
        "components": ["lorawan"],
    })

    board = library.board(design.board.library_id)
    radio = board.radio
    if radio is None:
        # The validator should already flag a LoRaWAN design on a non-radio
        # board; the generator just skips the lorawan block rather than emit
        # nonsense.
        return

    radio_block: dict[str, Any] = {
        "chip": radio.chip,
        "cs_pin":  radio.pins.cs,
        "rst_pin": radio.pins.rst,
    }
    # lorawan-for-esphome v0 constructed RadioLib's Module without calling
    # SPI.begin(sck, miso, mosi, cs), so it relied on Arduino's default SPI
    # bus -- which on arduino-esp32 is VSPI (18/19/23/5). TTGO LoRa32 v1 and
    # most LoRa boards wire the radio to non-VSPI pins (e.g. 5/19/27/18), so
    # the component returned ERR_CHIP_NOT_FOUND on real hardware. Once
    # upstream merges the patch that takes sck_pin/miso_pin/mosi_pin in the
    # radio schema and calls SPI.begin() before constructing the Module, we
    # emit them from the board library's `default_buses.spi` so the YAML
    # works on any board the studio supports.
    spi_default = board.default_buses.get("spi") if board.default_buses else None
    if spi_default:
        if spi_default.get("clk"):
            radio_block["sck_pin"] = spi_default["clk"]
        if spi_default.get("miso"):
            radio_block["miso_pin"] = spi_default["miso"]
        if spi_default.get("mosi"):
            radio_block["mosi_pin"] = spi_default["mosi"]
    if radio.pins.dio0:
        radio_block["dio0_pin"] = radio.pins.dio0
    if radio.pins.dio1:
        radio_block["dio1_pin"] = radio.pins.dio1
    if radio.pins.busy:
        radio_block["busy_pin"] = radio.pins.busy
    if radio.tcxo_voltage:
        radio_block["tcxo_voltage"] = radio.tcxo_voltage
    if radio.dio2_as_rf_switch:
        radio_block["dio2_as_rf_switch"] = radio.dio2_as_rf_switch

    overrides = lorawan_secrets or {}

    def _secret_or_literal(name: str) -> Any:
        value = overrides.get(name)
        return value if value else Secret(name)

    lorawan_block: dict[str, Any] = {
        "id": "lw",
        "region": lw.region,
        "sub_band": lw.sub_band,
        "dev_eui":  _secret_or_literal("dev_eui"),
        "join_eui": _secret_or_literal("join_eui"),
        "app_key":  _secret_or_literal("app_key"),
        "radio": radio_block,
    }
    out["lorawan"] = lorawan_block

    for field in lw.payload:
        out.setdefault("sensor", []).append({
            "platform": "lorawan",
            "lorawan_id": "lw",
            "sensor": field.sensor,
        })


def build_yaml_dict(
    design: Design,
    library: Library,
    *,
    lorawan_secrets: dict[str, str] | None = None,
) -> dict[str, Any]:
    board = library.board(design.board.library_id)
    out: dict[str, Any] = {}

    device_name = (design.fleet.device_name if design.fleet and design.fleet.device_name else design.id)
    out["esphome"] = {"name": device_name}

    chip_block: dict[str, Any] = {"board": board.platformio_board}
    if board.chip_variant.startswith("esp32"):
        # ESPHome unifies all ESP32 family variants (-C3, -S2, -S3, -C6,
        # -H2, ...) under a single top-level `esp32:` key. The variant is
        # specified inline via the `variant:` field; classic dual-core
        # Xtensa ESP32 is the default and omits it.
        chip_block["framework"] = {"type": design.board.framework}
        if board.chip_variant != "esp32":
            chip_block["variant"] = board.chip_variant.upper()
        out["esp32"] = chip_block
    else:
        out[board.chip_variant] = chip_block

    extras = dict(design.esphome_extras or {})
    out["logger"] = extras.pop("logger", {})

    # The external-component LoRaWAN path is *headless*. Field nodes are
    # typically out of WiFi range and on battery, and `wifi:` / `api:` /
    # network `ota:` default to `reboot_timeout: 15min` -- an unreachable
    # network reboot-loops the device, each reboot burns a fresh DevNonce
    # in the OTAA flow, and the device stops joining cleanly.
    # `captive_portal:` depends on `wifi:`. See lorawan-for-esphome README.
    lorawan_external = bool(design.lorawan and design.lorawan.payload)

    if design.fleet and design.fleet.secrets_ref and not lorawan_external:
        secrets = design.fleet.secrets_ref
        api_block: dict[str, Any] = {}
        if "api_key" in secrets:
            api_block["encryption"] = {"key": Secret(_secret_name(secrets["api_key"]))}
        out["api"] = api_block
        out["ota"] = [{"platform": "esphome"}]
        if "wifi_ssid" in secrets:
            wifi: dict[str, Any] = {"ssid": Secret(_secret_name(secrets["wifi_ssid"]))}
            wifi["password"] = Secret(_secret_name(secrets.get("wifi_password", "!secret wifi_password")))
            out["wifi"] = wifi

    if "captive_portal" in extras:
        cp = extras.pop("captive_portal")
        if not lorawan_external:
            out["captive_portal"] = cp if cp else {}
    # captive_portal entries silently dropped when LoRaWAN is active so an
    # example author who left it in esphome_extras doesn't have to scrub
    # it per-target. Also drop any wifi/api/ota the user might have set
    # via esphome_extras (header-level overrides).
    if lorawan_external:
        for k in ("wifi", "api", "ota", "captive_portal"):
            extras.pop(k, None)

    for bus in design.buses:
        if bus.type == "i2c":
            entry: dict[str, Any] = {"id": bus.id, "sda": bus.sda, "scl": bus.scl}
            if bus.frequency_hz:
                entry["frequency"] = _hz_to_freq(bus.frequency_hz)
            out.setdefault("i2c", []).append(entry)
        elif bus.type == "spi":
            spi_entry: dict[str, Any] = {"id": bus.id, "clk_pin": bus.clk}
            if bus.miso:
                spi_entry["miso_pin"] = bus.miso
            if bus.mosi:
                spi_entry["mosi_pin"] = bus.mosi
            out.setdefault("spi", []).append(spi_entry)
        elif bus.type == "i2s":
            i2s_entry: dict[str, Any] = {}
            if bus.lrclk:
                i2s_entry["i2s_lrclk_pin"] = bus.lrclk
            if bus.bclk:
                i2s_entry["i2s_bclk_pin"] = bus.bclk
            # ESPHome's i2s_audio block is a singleton, no id; keep the bus.id
            # in design.json for reference but don't emit it.
            out["i2s_audio"] = i2s_entry
        elif bus.type == "uart":
            uart_entry: dict[str, Any] = {"id": bus.id}
            if bus.rx:
                uart_entry["rx_pin"] = bus.rx
            if bus.tx:
                uart_entry["tx_pin"] = bus.tx
            if bus.baud_rate:
                uart_entry["baud_rate"] = bus.baud_rate
            if bus.parity:
                uart_entry["parity"] = bus.parity
            out.setdefault("uart", []).append(uart_entry)
        elif bus.type == "1wire":
            # Single-pin bus. ESPHome's `one_wire:` block lists each
            # physical wire by id; multiple DS18B20s on the same wire
            # share an id, so we emit the bus block here and the
            # component templates only refer to it via one_wire_id.
            wire_entry: dict[str, Any] = {
                "platform": "gpio",
                "pin": bus.pin,
                "id": bus.id,
            }
            out.setdefault("one_wire", []).append(wire_entry)

    auto_params = _lower_automations(design, library)
    for comp in design.components:
        _deep_merge(out, _render_component(comp, design, library, auto_params))

    _emit_lorawan_blocks(out, design, library, lorawan_secrets=lorawan_secrets)

    if extras:
        _deep_merge(out, extras)

    return out


# Two forms of YAML tag quoting that need fixing up:
#  1. tag-then-quote: `!secret 'api_key'` -- emitted by the Secret class.
#  2. quote-then-tag: `'!lambda return x;'` -- emitted by PyYAML when an ordinary
#     string starts with `!`, since it would otherwise be parsed as a tag.
# We only strip quotes when the inner content is safe as a plain YAML scalar;
# otherwise the unquoted form would parse as malformed mapping/comment syntax.
_TAGGED_THEN_QUOTED = re.compile(r"!(secret|lambda) '([^']*)'")
_QUOTED_TAG = re.compile(r"'(!(?:secret|lambda) [^']*)'")


def _plain_scalar_safe(content: str) -> bool:
    if ": " in content or " #" in content or "\t" in content:
        return False
    if content.startswith(("[", "{", "&", "*", "?", ",", "-")):
        return False
    return True


def _unquote_tagged(match: re.Match[str]) -> str:
    tag, content = match.group(1), match.group(2)
    if _plain_scalar_safe(content):
        return f"!{tag} {content}"
    return match.group(0)


def _unquote_quoted_tag(match: re.Match[str]) -> str:
    inner = match.group(1)  # e.g. "!lambda return x;"
    _tag, _, content = inner.partition(" ")
    if _plain_scalar_safe(content):
        return inner
    return match.group(0)


def render_yaml(
    design: Design,
    library: Library,
    *,
    lorawan_secrets: dict[str, str] | None = None,
) -> str:
    data = build_yaml_dict(design, library, lorawan_secrets=lorawan_secrets)
    text = yaml.dump(
        data,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=120,
    )
    text = _TAGGED_THEN_QUOTED.sub(_unquote_tagged, text)
    text = _QUOTED_TAG.sub(_unquote_quoted_tag, text)
    return text
