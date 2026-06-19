"""Intent-to-device synthesis (phase 1): validate the `automations` graph.

Phase 1 covers declarative event -> action only (the `button_toggles_light`
shape). Each automation's trigger references a component that must `provide`
the named event in its library capability block; each action references a
component that must `accept` the named action. The validator surfaces dangling
references as permissive warnings (CLAUDE.md: warnings, don't block) so a
half-authored automation doesn't refuse to render -- it just doesn't fire.

The generator's lowering (``yaml_gen._lower_automations``) drops the same
unresolved entries silently rather than emit invalid YAML, so the warnings here
are what tells the user *why* nothing happened.
"""
from __future__ import annotations

from wirestudio.library import Library
from wirestudio.model import Design, DesignWarning


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
    """
    out: list[DesignWarning] = []
    by_id = {c.id: c for c in design.components}
    for auto in design.automations:
        trig = auto.trigger
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
    return out
