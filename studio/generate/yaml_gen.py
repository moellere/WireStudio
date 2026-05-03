from __future__ import annotations

import re
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined

from studio.library import Library
from studio.model import Bus, Component, Design


class Secret(str):
    """String wrapper that dumps as a YAML `!secret <name>` tag."""


def _secret_representer(dumper: yaml.Dumper, data: Secret) -> yaml.ScalarNode:
    return dumper.represent_scalar("!secret", str(data), style="")


yaml.add_representer(Secret, _secret_representer)
yaml.SafeDumper.add_representer(Secret, _secret_representer)


_jinja = Environment(undefined=StrictUndefined, keep_trailing_newline=False)


def _bus_for(component_id: str, design: Design) -> Bus | None:
    for c in design.connections:
        if c.component_id == component_id and c.target.kind == "bus":
            for b in design.buses:
                if b.id == c.target.bus_id:
                    return b
    return None


def _pins_for(component_id: str, design: Design) -> dict[str, str]:
    return {
        c.pin_role: c.target.pin
        for c in design.connections
        if c.component_id == component_id and c.target.kind == "gpio"
    }


def _deep_merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if k in dst and isinstance(dst[k], list) and isinstance(v, list):
            dst[k].extend(v)
        elif k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def _render_component(comp: Component, design: Design, library: Library) -> dict[str, Any]:
    lib_comp = library.component(comp.library_id)
    template_str = lib_comp.esphome.yaml_template
    if not template_str.strip():
        return {}
    bus = _bus_for(comp.id, design)
    ctx = {
        "id": comp.id,
        "label": comp.label,
        "params": dict(comp.params),
        "pins": _pins_for(comp.id, design),
        "bus": bus.model_dump() if bus else None,
    }
    rendered = _jinja.from_string(template_str).render(**ctx)
    parsed = yaml.safe_load(rendered)
    return parsed or {}


def _hz_to_freq(hz: int) -> str:
    if hz % 1_000_000 == 0:
        return f"{hz // 1_000_000}MHz"
    if hz % 1000 == 0:
        return f"{hz // 1000}kHz"
    return f"{hz}Hz"


def _secret_name(ref: str) -> str:
    return ref.removeprefix("!secret ").strip()


def build_yaml_dict(design: Design, library: Library) -> dict[str, Any]:
    board = library.board(design.board.library_id)
    out: dict[str, Any] = {}

    device_name = (design.fleet.device_name if design.fleet and design.fleet.device_name else design.id)
    out["esphome"] = {"name": device_name}

    out[board.chip_variant] = {
        "board": board.platformio_board,
        "framework": {"type": design.board.framework},
    }

    extras = dict(design.esphome_extras or {})
    out["logger"] = extras.pop("logger", {})

    if design.fleet and design.fleet.secrets_ref:
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
        out["captive_portal"] = cp if cp else {}

    for bus in design.buses:
        if bus.type == "i2c":
            entry: dict[str, Any] = {"id": bus.id, "sda": bus.sda, "scl": bus.scl}
            if bus.frequency_hz:
                entry["frequency"] = _hz_to_freq(bus.frequency_hz)
            out.setdefault("i2c", []).append(entry)
        elif bus.type == "spi":
            out.setdefault("spi", []).append({
                "id": bus.id,
                "clk_pin": bus.clk,
                "miso_pin": bus.miso,
                "mosi_pin": bus.mosi,
            })

    for comp in design.components:
        _deep_merge(out, _render_component(comp, design, library))

    for k, v in extras.items():
        out[k] = v

    return out


_SECRET_QUOTED = re.compile(r"!secret '([^']*)'")


def render_yaml(design: Design, library: Library) -> str:
    data = build_yaml_dict(design, library)
    text = yaml.dump(
        data,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=120,
    )
    return _SECRET_QUOTED.sub(r"!secret \1", text)
