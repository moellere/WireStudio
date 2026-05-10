"""Constrained tool surface the agent can call.

Each tool is a pair: a Claude-shaped JSON schema + a Python implementation
that mutates a single `design` dict in place. Tools never call the network,
never load files outside the library, and never execute user-provided code.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from wirestudio.csp.compatibility import check_pin_compatibility
from wirestudio.csp.pin_solver import solve_pins as _solve_pins
from wirestudio.designs.seed import add_component_with_connections
from wirestudio.generate.ascii_gen import render_ascii
from wirestudio.generate.yaml_gen import render_yaml
from wirestudio.library import Library
from wirestudio.model import Design
from wirestudio.recommend.recommender import Constraints, recommend_components


# ---------------------------------------------------------------------------
# Tool schemas (Claude wire format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "search_components",
        "description": (
            "Fuzzy-search the component library by name, category, use_case, or "
            "alias. Returns up to 10 matches with their library_id, name, "
            "category, and required ESPHome integrations. Use this before "
            "calling add_component so you never invent a library_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text query."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_boards",
        "description": "List every board in the library with its mcu, chip_variant, framework, and platformio_board.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "set_board",
        "description": (
            "Replace the design's board. Looks up the library board by id and "
            "updates `design.board.{library_id, mcu, framework}`. Does NOT "
            "translate existing pin references (e.g. native GPIO names) -- "
            "those will surface as warnings if the new board can't accept them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "library_id": {"type": "string", "description": "Board library id, e.g. esp32-devkitc-v4."},
            },
            "required": ["library_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "add_component",
        "description": (
            "Add a component instance to the design. Auto-generates a unique "
            "instance_id (or use `instance_id_hint` to suggest one), sets "
            "`label` (default = library component name), copies any provided "
            "`params`, and creates one connection per pin in the library "
            "entry. Power pins go to a matching rail by voltage; bus pins "
            "(I2C/SPI/UART/I2S) link to the first matching bus in the design "
            "or an empty placeholder. Returns the new instance_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "library_id": {"type": "string"},
                "label": {"type": "string"},
                "instance_id_hint": {"type": "string"},
                "params": {"type": "object", "additionalProperties": True},
            },
            "required": ["library_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "remove_component",
        "description": (
            "Remove a component instance and all connections originating from "
            "it. Connections that *target* this instance via expander_id are "
            "left as orphans (they surface in the design but have no owner)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string"},
            },
            "required": ["instance_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_param",
        "description": (
            "Set a single param on a component instance. Pass `value: null` to "
            "delete the param entirely. The schema for each component's params "
            "lives in the library entry's `params_schema` -- inspect with "
            "search_components or get_component first if unsure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string"},
                "key": {"type": "string"},
                "value": {"description": "Any JSON value, or null to delete the key."},
            },
            "required": ["instance_id", "key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_connection",
        "description": (
            "Set the target of a single connection identified by "
            "`component_id` + `pin_role`. The `target` shape mirrors the "
            "design.json schema: rail = {kind:'rail', rail:'5V'}, gpio = "
            "{kind:'gpio', pin:'GPIO13'}, bus = {kind:'bus', bus_id:'i2c0'}, "
            "expander_pin = {kind:'expander_pin', expander_id:'mcp_hub', "
            "number:0, mode:'INPUT_PULLUP', inverted:true}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "component_id": {"type": "string"},
                "pin_role": {"type": "string"},
                "target": {"type": "object"},
            },
            "required": ["component_id", "pin_role", "target"],
            "additionalProperties": False,
        },
    },
    {
        "name": "add_bus",
        "description": (
            "Add a bus to the design. `type` must be one of i2c / spi / uart "
            "/ 1wire / i2s. Other fields depend on the type: i2c needs "
            "sda + scl, spi needs clk + miso? + mosi?, uart needs rx + tx + "
            "baud_rate, i2s needs lrclk + bclk."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Bus id, e.g. i2c0."},
                "type": {"type": "string", "enum": ["i2c", "spi", "uart", "1wire", "i2s"]},
                "sda": {"type": "string"},
                "scl": {"type": "string"},
                "frequency_hz": {"type": "integer"},
                "miso": {"type": "string"},
                "mosi": {"type": "string"},
                "clk": {"type": "string"},
                "cs": {"type": "string"},
                "rx": {"type": "string"},
                "tx": {"type": "string"},
                "baud_rate": {"type": "integer"},
                "lrclk": {"type": "string"},
                "bclk": {"type": "string"},
            },
            "required": ["id", "type"],
            "additionalProperties": False,
        },
    },
    {
        "name": "render",
        "description": (
            "Render the current design to ESPHome YAML + ASCII diagram. "
            "Returns both as strings. Read-only. Use this to verify your "
            "edits before wrapping up the turn."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "validate",
        "description": (
            "Validate the design against the JSON schema and library. "
            "Returns ok=true plus a summary, or ok=false with the failing "
            "field path + message. Read-only."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "recommend",
        "description": (
            "Rank library components against a free-text capability query "
            "(e.g. 'motion detection', 'temperature humidity', 'rfid'). "
            "Returns up to `limit` candidates with their electrical "
            "metadata, an in-examples count (a proxy for battle-tested), "
            "and a one-line rationale per pick. Read-only -- doesn't add "
            "anything to the design. Use this when the user asks for "
            "open-ended component suggestions; for known library_ids use "
            "search_components or add_component directly. Optionally pass "
            "constraints (voltage rail, max peak current, required bus, "
            "excluded categories) to filter before ranking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10},
                "constraints": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "voltage": {"type": "number", "description": "Rail voltage the part will run on."},
                        "max_current_ma_peak": {"type": "number"},
                        "required_bus": {"type": "string", "enum": ["i2c", "spi", "uart", "1wire", "i2s"]},
                        "excluded_categories": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "solve_pins",
        "description": (
            "Auto-assign every unbound connection: gpio with empty pin -> "
            "a board GPIO matching the library pin's capability; bus with "
            "empty bus_id -> first matching design bus; expander_pin with "
            "empty expander_id -> next free pin on the first io_expander. "
            "Doesn't reassign already-bound pins. Returns the count of "
            "assignments made, any unresolved connections, and any "
            "conflict / current-budget warnings the solver detected. "
            "Mutates the design."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


# ---------------------------------------------------------------------------
# Implementations: each takes (design, library, **input) and returns a value
# the agent should see as the tool result. Mutates `design` in place when
# applicable.
# ---------------------------------------------------------------------------


def _run_search_components(design: dict, library: Library, *, query: str) -> dict:
    q = query.strip().lower()
    results = []
    for c in library.list_components():
        haystacks = [
            c.id, c.name, c.category,
            *c.use_cases, *c.aliases,
        ]
        if any(q in h.lower() for h in haystacks):
            results.append({
                "library_id": c.id,
                "name": c.name,
                "category": c.category,
                "use_cases": list(c.use_cases),
                "required_components": list(c.esphome.required_components),
                "current_ma_typical": c.electrical.current_ma_typical,
                "current_ma_peak": c.electrical.current_ma_peak,
            })
    return {"matches": results[:10], "total": len(results)}


def _run_list_boards(design: dict, library: Library) -> dict:
    return {
        "boards": [
            {
                "library_id": b.id,
                "name": b.name,
                "mcu": b.mcu,
                "chip_variant": b.chip_variant,
                "framework": b.framework,
                "platformio_board": b.platformio_board,
                "flash_size_mb": b.flash_size_mb,
            }
            for b in library.list_boards()
        ]
    }


def _run_set_board(design: dict, library: Library, *, library_id: str) -> dict:
    board = library.board(library_id)  # raises FileNotFoundError if unknown
    design["board"] = {
        **(design.get("board") or {}),
        "library_id": board.id,
        "mcu": board.mcu,
        "framework": board.framework,
    }
    return {"ok": True, "board": {"library_id": board.id, "mcu": board.mcu}}


def _run_add_component(
    design: dict, library: Library, *,
    library_id: str,
    label: str | None = None,
    instance_id_hint: str | None = None,
    params: dict | None = None,
) -> dict:
    instance_id, _ = add_component_with_connections(
        design, library,
        library_id=library_id,
        label=label,
        instance_id_hint=instance_id_hint,
        params=params,
    )
    return {"ok": True, "instance_id": instance_id}


def _run_remove_component(design: dict, library: Library, *, instance_id: str) -> dict:
    components = design.get("components") or []
    if not any(c["id"] == instance_id for c in components):
        return {"ok": False, "error": f"unknown instance_id '{instance_id}'"}
    design["components"] = [c for c in components if c["id"] != instance_id]
    design["connections"] = [
        c for c in (design.get("connections") or []) if c.get("component_id") != instance_id
    ]
    return {"ok": True}


def _run_set_param(
    design: dict, library: Library, *, instance_id: str, key: str, value: Any = None,
) -> dict:
    components = design.get("components") or []
    target = next((c for c in components if c["id"] == instance_id), None)
    if target is None:
        return {"ok": False, "error": f"unknown instance_id '{instance_id}'"}
    params = target.setdefault("params", {})
    if value is None:
        params.pop(key, None)
        return {"ok": True, "deleted": key}
    params[key] = value
    return {"ok": True, "set": {key: value}}


def _run_set_connection(
    design: dict, library: Library, *, component_id: str, pin_role: str, target: dict,
) -> dict:
    connections = design.get("connections") or []
    for c in connections:
        if c.get("component_id") == component_id and c.get("pin_role") == pin_role:
            c["target"] = target
            return {"ok": True, "updated": True}
    # No existing connection -- append a new one.
    connections.append({"component_id": component_id, "pin_role": pin_role, "target": target})
    design["connections"] = connections
    return {"ok": True, "created": True}


def _run_add_bus(design: dict, library: Library, **fields: Any) -> dict:
    buses = design.setdefault("buses", [])
    if any(b.get("id") == fields["id"] for b in buses):
        return {"ok": False, "error": f"bus id '{fields['id']}' already exists"}
    buses.append({k: v for k, v in fields.items() if v is not None})
    return {"ok": True}


def _run_render(design: dict, library: Library) -> dict:
    try:
        d = Design.model_validate(design)
    except Exception as e:
        return {"ok": False, "error": f"design failed validation: {e}"}
    try:
        return {"ok": True, "yaml": render_yaml(d, library), "ascii": render_ascii(d, library)}
    except (FileNotFoundError, ValueError) as e:
        return {"ok": False, "error": str(e)}


def _run_recommend(
    design: dict, library: Library, *,
    query: str,
    limit: int = 10,
    constraints: dict | None = None,
) -> dict:
    cobj = Constraints(**(constraints or {}))
    results = recommend_components(library, query, constraints=cobj, limit=limit)
    return {
        "ok": True,
        "query": query,
        "matches": [
            {
                "library_id": r.library_id,
                "name": r.name,
                "category": r.category,
                "use_cases": r.use_cases,
                "required_components": r.required_components,
                "current_ma_typical": r.current_ma_typical,
                "current_ma_peak": r.current_ma_peak,
                "vcc_min": r.vcc_min,
                "vcc_max": r.vcc_max,
                "score": r.score,
                "in_examples": r.in_examples,
                "rationale": r.rationale,
                "notes": r.notes,
            }
            for r in results
        ],
    }


def _run_solve_pins(design: dict, library: Library) -> dict:
    result = _solve_pins(design, library)
    # Mutate the caller's dict in place to mirror the result design.
    design.clear()
    design.update(result.design)
    return {
        "ok": True,
        "assigned": [
            {
                "component_id": a.component_id,
                "pin_role": a.pin_role,
                "old_target": a.old_target,
                "new_target": a.new_target,
            }
            for a in result.assigned
        ],
        "unresolved": [{"code": w.code, "text": w.text} for w in result.unresolved],
        "warnings": [{"level": w.level, "code": w.code, "text": w.text} for w in result.warnings],
    }


def _run_validate(design: dict, library: Library) -> dict:
    try:
        d = Design.model_validate(design)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    # Try a render to surface unrenderable-but-validating designs (e.g. missing bus).
    try:
        render_yaml(d, library)
    except (FileNotFoundError, ValueError) as e:
        return {"ok": False, "error": str(e), "schema_ok": True}
    compat = check_pin_compatibility(design, library)
    return {
        "ok": True,
        "design_id": d.id,
        "name": d.name,
        "components": len(d.components),
        "buses": len(d.buses),
        "connections": len(d.connections),
        "warnings": [w.model_dump() for w in d.warnings],
        "compatibility_warnings": [
            {
                "severity": w.severity, "code": w.code, "pin": w.pin,
                "component_id": w.component_id, "pin_role": w.pin_role,
                "message": w.message,
            }
            for w in compat
        ],
    }


TOOL_HANDLERS: dict[str, Callable[..., Any]] = {
    "search_components": _run_search_components,
    "list_boards": _run_list_boards,
    "set_board": _run_set_board,
    "add_component": _run_add_component,
    "remove_component": _run_remove_component,
    "set_param": _run_set_param,
    "set_connection": _run_set_connection,
    "add_bus": _run_add_bus,
    "render": _run_render,
    "validate": _run_validate,
    "recommend": _run_recommend,
    "solve_pins": _run_solve_pins,
}


def execute_tool(name: str, tool_input: dict, design: dict, library: Library) -> tuple[str, bool]:
    """Dispatch a single tool call. Returns (json_str_for_claude, is_error).

    `design` is mutated in place by mutating tools. Errors (unknown tool,
    library miss, validation failure) come back as `is_error=True` so the
    model knows to recover or apologize instead of pressing on.
    """
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"unknown tool: {name}"}), True
    try:
        result = handler(design, library, **tool_input)
    except FileNotFoundError as e:
        return json.dumps({"error": str(e)}), True
    except TypeError as e:
        return json.dumps({"error": f"bad arguments: {e}"}), True
    return json.dumps(result, default=str), False
