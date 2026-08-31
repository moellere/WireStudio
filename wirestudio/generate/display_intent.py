"""Display content intent: lower `params.show` to a display lambda.

Adding a display used to produce a dark panel unless the user wrote the
ESPHome lambda by hand. `show` is the declarative alternative: a list of
widgets the design binds to other components' values, lowered here into
the `params.lambda_` string (plus a `font:` block for pixel displays and
a `time:` block when a time widget appears). The raw lambda escape hatch
still wins: a design that sets `lambda_` explicitly is left alone.

Widget shapes:
  {"kind": "text", "text": "Attic"}
  {"kind": "value", "source": "climate", "channel": "temperature",
   "label": "T", "format": "%.1f", "unit": "C"}
  {"kind": "time", "format": "%H:%M"}

Value references follow the template id convention: a single-value
sensor's ESPHome id is the component id; a multi-channel sensor's is
`<component id>_<channel>`.
"""
from __future__ import annotations

from typing import Any

from wirestudio.library import Library
from wirestudio.model import Design, DesignWarning

_FONT_ID = "ws_show_font"
_TIME_ID = "ws_show_time"
_PIXEL_LINE_HEIGHT = 16
_PIXEL_FONT_SIZE = 14


def _value_ref(widget: dict) -> str:
    source = str(widget.get("source", ""))
    channel = widget.get("channel")
    return f"{source}_{channel}" if channel else source


def _fmt(widget: dict, default_format: str = "%.1f") -> tuple[str, str]:
    """(printf format string, args) for one value widget."""
    label = widget.get("label")
    fmt = str(widget.get("format", default_format))
    unit = str(widget.get("unit", ""))
    text = f"{label} {fmt}{unit}" if label else f"{fmt}{unit}"
    return text, f"id({_value_ref(widget)}).state"


def _pixel_lambda(widgets: list[dict]) -> str:
    lines = ["int y = 0;"]
    for w in widgets:
        kind = w.get("kind")
        if kind == "text":
            lines.append(f'it.printf(0, y, id({_FONT_ID}), "{w.get("text", "")}");')
        elif kind == "value":
            text, arg = _fmt(w)
            lines.append(f'it.printf(0, y, id({_FONT_ID}), "{text}", {arg});')
        elif kind == "time":
            fmt = w.get("format", "%H:%M")
            lines.append(
                f'it.strftime(0, y, id({_FONT_ID}), "{fmt}", id({_TIME_ID}).now());'
            )
        lines.append(f"y += {_PIXEL_LINE_HEIGHT};")
    return "\n".join(lines)


def _character_lambda(widgets: list[dict]) -> str:
    lines = []
    for row, w in enumerate(widgets):
        kind = w.get("kind")
        if kind == "text":
            lines.append(f'it.printf(0, {row}, "{w.get("text", "")}");')
        elif kind == "value":
            text, arg = _fmt(w)
            lines.append(f'it.printf(0, {row}, "{text}", {arg});')
        elif kind == "time":
            fmt = w.get("format", "%H:%M")
            lines.append(f'it.strftime(0, {row}, "{fmt}", id({_TIME_ID}).now());')
    return "\n".join(lines)


def _seven_segment_lambda(widgets: list[dict]) -> str:
    # One value (or clock) fits on a digit display; extra widgets were
    # already warned about by the validator.
    for w in widgets:
        kind = w.get("kind")
        if kind == "value":
            text, arg = _fmt(w, default_format="%4.0f")
            return f'it.printf("{text}", {arg});'
        if kind == "time":
            fmt = w.get("format", "%H.%M")
            return f'it.strftime("{fmt}", id({_TIME_ID}).now());'
        if kind == "text":
            return f'it.print("{w.get("text", "")}");'
    return 'it.print("----");'


_DIALECTS = {
    "pixel": _pixel_lambda,
    "character": _character_lambda,
    "seven_segment": _seven_segment_lambda,
}

# tm1637's template reads `params.lambda`; every other display reads
# `params.lambda_`.
_LAMBDA_PARAM_OVERRIDES = {"tm1637": "lambda"}


def lower_show(design: Design, library: Library) -> tuple[dict[str, dict], dict]:
    """Return ({component_id: params patch}, extra top-level blocks).

    The patch sets the display's lambda param from its `show` widgets;
    extras carry the shared `font:` / `time:` blocks when any lowered
    display needs them. Unresolvable widgets still render (a printf of a
    missing id fails at the esphome gate, not silently) -- the validator
    is what explains the problem to the user.
    """
    patches: dict[str, dict] = {}
    extras: dict[str, Any] = {}
    needs_font = False
    needs_time = False

    for comp in design.components:
        params = comp.params or {}
        widgets = params.get("show")
        if not isinstance(widgets, list) or not widgets:
            continue
        try:
            lib_comp = library.component(comp.library_id)
        except FileNotFoundError:
            continue
        dialect = lib_comp.esphome.display_dialect
        render = _DIALECTS.get(dialect or "")
        if render is None:
            continue
        lambda_param = _LAMBDA_PARAM_OVERRIDES.get(comp.library_id, "lambda_")
        if lambda_param in params:
            continue  # an explicit lambda wins over show
        patches[comp.id] = {lambda_param: render(widgets)}
        if dialect == "pixel":
            needs_font = True
        if any(w.get("kind") == "time" for w in widgets):
            needs_time = True

    if needs_font:
        extras["font"] = [
            {"file": "gfonts://Roboto", "id": _FONT_ID, "size": _PIXEL_FONT_SIZE}
        ]
    if needs_time:
        extras["time"] = [{"platform": "homeassistant", "id": _TIME_ID}]
    return patches, extras


def validate_show(design: Design, library: Library) -> list[DesignWarning]:
    """Permissive checks over every display's `show` widgets."""
    out: list[DesignWarning] = []
    by_id = {c.id: c for c in design.components}
    for comp in design.components:
        widgets = (comp.params or {}).get("show")
        if not isinstance(widgets, list) or not widgets:
            continue
        try:
            lib_comp = library.component(comp.library_id)
        except FileNotFoundError:
            continue
        dialect = lib_comp.esphome.display_dialect
        if dialect not in _DIALECTS:
            out.append(DesignWarning(
                level="warn", code="show_not_a_display",
                text=(f"{comp.id}: params.show is set but {comp.library_id!r} "
                      f"declares no display dialect; nothing will be lowered"),
            ))
            continue
        if dialect == "seven_segment" and len(widgets) > 1:
            out.append(DesignWarning(
                level="warn", code="show_too_many_widgets",
                text=(f"{comp.id}: a digit display shows one widget; "
                      f"{len(widgets)} given, only the first value/time renders"),
            ))
        for w in widgets:
            if not isinstance(w, dict):
                continue
            kind = w.get("kind")
            if kind not in ("text", "value", "time"):
                out.append(DesignWarning(
                    level="warn", code="show_unknown_widget",
                    text=f"{comp.id}: unknown show widget kind {kind!r}",
                ))
                continue
            if kind != "value":
                continue
            source = by_id.get(str(w.get("source", "")))
            if source is None:
                out.append(DesignWarning(
                    level="warn", code="show_unknown_source",
                    text=(f"{comp.id}: show widget references component "
                          f"{w.get('source')!r} which is not in the design"),
                ))
                continue
            try:
                src_lib = library.component(source.library_id)
            except FileNotFoundError:
                continue
            cap = src_lib.capability
            value_channels = [
                p.channel for p in (cap.provides if cap else [])
                if p.kind == "value"
            ]
            if not value_channels:
                out.append(DesignWarning(
                    level="warn", code="show_source_not_a_sensor",
                    text=(f"{comp.id}: show widget source {source.id!r} "
                          f"({source.library_id}) provides no value to display"),
                ))
                continue
            channel = w.get("channel")
            declared = [c for c in value_channels if c]
            if channel and declared and channel not in declared:
                out.append(DesignWarning(
                    level="warn", code="show_unknown_channel",
                    text=(f"{comp.id}: {source.id!r} has no value channel "
                          f"{channel!r}; declared: {', '.join(declared)}"),
                ))
    return out
