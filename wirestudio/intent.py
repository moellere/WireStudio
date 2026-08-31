"""Intent-to-device synthesis: validate the `automations` graph.

Each automation's trigger references a component that must `provide` the
named event in its library capability block; each action references a
component that must `accept` the named action. The validator surfaces
dangling references as permissive warnings (CLAUDE.md: warnings, don't
block) so a half-authored automation doesn't refuse to render -- it just
doesn't fire.

The generator's lowering (``yaml_gen._lower_automations``) drops the same
unresolved entries silently rather than emit invalid YAML, so the warnings here
are what tells the user *why* nothing happened.
"""
from __future__ import annotations

from wirestudio.library import Library
from wirestudio.model import Design, DesignWarning

# Curated RTTTL melodies an automation can name via `args: {song: ...}`
# on the rtttl `play` action -- the lowering substitutes the full string.
# Reviewed recipes, not free-handed RTTTL in every design.
MELODIES: dict[str, str] = {
    "beep": "beep:d=8,o=6,b=180:c",
    "two_beep": "twobeep:d=8,o=6,b=180:c,p,c",
    "success": "success:d=16,o=6,b=140:c,e,g,4c7",
    "failure": "failure:d=16,o=6,b=140:c7,g,e,4c",
    "alarm": "alarm:d=8,o=6,b=160:c,p,c,p,c,p,c,p,c,p,c",
    "doorbell": "doorbell:d=4,o=5,b=100:e6,8p,c6",
    "nokia": "nokia:d=4,o=5,b=180:8e6,8d6,f#,g#,8c#6,8b,d,e,8b,8a,c#,e,2a",
    "mario": "mario:d=4,o=5,b=140:16e6,16e6,32p,8e6,16c6,8e6,8g6,8p,8g,8p",
}


def validate_automations(design: Design, library: Library) -> list[DesignWarning]:
    """Permissive checks over `design.automations`. Returns DesignWarnings;
    never raises. Each warning's `code` is one of:

    - ``automation_unknown_component``: trigger or action references an id
      that isn't in `design.components`.
    - ``automation_component_no_capability``: the referenced component's
      library entry has no `capability` block (so it can't trigger or act).
    - ``automation_unknown_event``: the event name isn't in the trigger
      component's `capability.provides`.
    - ``automation_unknown_action``: the action name isn't in the action
      component's `capability.accepts`.
    - ``automation_bounds_require_value_range``: the trigger sets
      `above` / `below` on an event other than `on_value_range`.
    - ``automation_value_range_needs_bounds``: the trigger event is
      `on_value_range` but neither `above` nor `below` is set, so the
      range would fire on every reading.
    - ``automation_unknown_predicate``: a condition names a predicate not
      in the referenced component's `capability.checks`.
    """
    out: list[DesignWarning] = []
    by_id = {c.id: c for c in design.components}
    for auto in design.automations:
        trig = auto.trigger
        has_bounds = trig.above is not None or trig.below is not None
        if has_bounds and trig.event != "on_value_range":
            out.append(DesignWarning(
                level="warn", code="automation_bounds_require_value_range",
                text=(f"automation {auto.id!r}: trigger sets above/below but "
                      f"event is {trig.event!r}, not 'on_value_range' -- the "
                      f"bounds would be silently dropped"),
            ))
        if trig.event == "on_value_range" and not has_bounds:
            out.append(DesignWarning(
                level="warn", code="automation_value_range_needs_bounds",
                text=(f"automation {auto.id!r}: event is 'on_value_range' but "
                      f"neither above nor below is set; the range would fire "
                      f"on every reading"),
            ))
        trig_comp = by_id.get(trig.component_id)
        if trig_comp is None:
            out.append(DesignWarning(
                level="warn", code="automation_unknown_component",
                text=(f"automation {auto.id!r}: trigger component "
                      f"{trig.component_id!r} is not in the design"),
            ))
        else:
            try:
                lib_comp = library.component(trig_comp.library_id)
            except FileNotFoundError:
                # Unknown library_id surfaces from the core validators.
                lib_comp = None
            if lib_comp is not None:
                cap = lib_comp.capability
                if cap is None:
                    out.append(DesignWarning(
                        level="warn", code="automation_component_no_capability",
                        text=(f"automation {auto.id!r}: trigger component "
                              f"{trig.component_id!r} (library_id="
                              f"{trig_comp.library_id!r}) has no capability "
                              f"block and can't trigger automations"),
                    ))
                else:
                    trig_channel = trig.channel
                    match = next(
                        (p for p in cap.provides
                         if p.event == trig.event and (p.channel or None) == (trig_channel or None)),
                        None,
                    )
                    if match is None:
                        provided = ", ".join(
                            f"{p.channel}.{p.event}" if p.channel else p.event
                            for p in cap.provides
                        ) or "(none)"
                        suffix = (
                            f"event {trig.event!r} on channel {trig_channel!r}"
                            if trig_channel else f"event {trig.event!r}"
                        )
                        out.append(DesignWarning(
                            level="warn", code="automation_unknown_event",
                            text=(f"automation {auto.id!r}: component "
                                  f"{trig.component_id!r} does not provide "
                                  f"{suffix}; provides: {provided}"),
                        ))

        for cond in auto.conditions:
            cond_comp = by_id.get(cond.component_id)
            if cond_comp is None:
                out.append(DesignWarning(
                    level="warn", code="automation_unknown_component",
                    text=(f"automation {auto.id!r}: condition component "
                          f"{cond.component_id!r} is not in the design"),
                ))
                continue
            try:
                cond_lib = library.component(cond_comp.library_id)
            except FileNotFoundError:
                continue
            cap = cond_lib.capability
            if cap is None:
                out.append(DesignWarning(
                    level="warn", code="automation_component_no_capability",
                    text=(f"automation {auto.id!r}: condition component "
                          f"{cond.component_id!r} (library_id="
                          f"{cond_comp.library_id!r}) has no capability block "
                          f"and can't be a condition source"),
                ))
                continue
            if not any(c.predicate == cond.predicate for c in cap.checks):
                supported = ", ".join(c.predicate for c in cap.checks) or "(none)"
                out.append(DesignWarning(
                    level="warn", code="automation_unknown_predicate",
                    text=(f"automation {auto.id!r}: component "
                          f"{cond.component_id!r} does not support predicate "
                          f"{cond.predicate!r}; supports: {supported}"),
                ))

        for act in auto.actions:
            act_comp = by_id.get(act.component_id)
            if act_comp is None:
                out.append(DesignWarning(
                    level="warn", code="automation_unknown_component",
                    text=(f"automation {auto.id!r}: action component "
                          f"{act.component_id!r} is not in the design"),
                ))
                continue
            try:
                act_lib = library.component(act_comp.library_id)
            except FileNotFoundError:
                continue
            cap = act_lib.capability
            if cap is None:
                out.append(DesignWarning(
                    level="warn", code="automation_component_no_capability",
                    text=(f"automation {auto.id!r}: action component "
                          f"{act.component_id!r} (library_id="
                          f"{act_comp.library_id!r}) has no capability block "
                          f"and can't be an automation target"),
                ))
                continue
            if not any(a.action == act.action for a in cap.accepts):
                accepted = ", ".join(a.action for a in cap.accepts) or "(none)"
                out.append(DesignWarning(
                    level="warn", code="automation_unknown_action",
                    text=(f"automation {auto.id!r}: component "
                          f"{act.component_id!r} does not accept action "
                          f"{act.action!r}; accepts: {accepted}"),
                ))
            song = act.args.get("song")
            if song is not None and song not in MELODIES:
                out.append(DesignWarning(
                    level="warn", code="automation_unknown_song",
                    text=(f"automation {auto.id!r}: unknown song {song!r}; "
                          f"known: {', '.join(sorted(MELODIES))}"),
                ))
            if act.action == "play" and song is None and "rtttl" not in act.args:
                out.append(DesignWarning(
                    level="warn", code="automation_play_needs_song",
                    text=(f"automation {auto.id!r}: play on "
                          f"{act.component_id!r} needs args.song (a named "
                          f"melody) or args.rtttl (a raw RTTTL string)"),
                ))
    return out
