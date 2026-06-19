# Intent-to-device synthesis (design direction)

Status: **phases 1 + 1.5a + 1.5b + 2 + 3 + 4 + 5 shipped** (declarative
event→action, broader library coverage, single-output sensor triggers,
value→transform→action, multi-channel sensor triggers, on_value_range
threshold bounds, condition gating). On `main`: the `capability` library block, the
`automations` schema in `design.json` (with `trigger.channel`,
`trigger.above` / `.below`, `actions[].transform`), generator lowering with
`!lambda` transforms, per-channel passthroughs and `{above, below, then}`
range entries, the permissive validator (now catching bounds-on-wrong-event
and range-without-bounds), and five worked examples (`button-toggles-light`,
`motion-turns-on-light`, `encoder-drives-stepper`, `temp-turns-on-fan`,
`temp-above-turns-on-fan`). Twenty-nine components carry `capability`
annotations; the seven phase-3 multi-channel environmental sensors now also
expose `on_value_range` per channel, so a threshold trigger composes with the
channel selector cleanly.

Phase 4 carries threshold bounds on the trigger; the bme280 example fires
`switch.turn_on: fan` when temperature crosses 28°C and the lowering emits
ESPHome's `on_value_range: - above: 28.0\n  then: [...]` shape inside the
right sub-block. The remaining unannotated multi-output components
(mpu6050/mpu6886 IMUs, cse7766/hlw8012/bl0906/sdm_meter power meters) carry
too many channels to enumerate without a further design call. Condition
gating, multi-device topology, and a live `esphome config` authoring loop
arrive in later phases per *Suggested phasing* below.

This document was the agreed plan; per-phase work updates this status line in
place rather than appending a new file each time.

## Problem

Today the MCP/agent surface is *structural*: pick a board, add components, wire
pins, solve pins, render YAML. That gets the user correct hardware. It does not
get them a device that *does the thing they asked for* -- "push a button and a
light turns on", "detect motion", "turn this knob and the motor follows". The
behavior -- ESPHome's automations, triggers, actions, lambdas, and the
cross-entity wiring between them -- is the missing layer.

The goal: the model interpreting a request must know enough about *how ESPHome
functions* to (a) decide which components are needed, (b) wire them together --
physically and behaviorally -- to produce the requested outcome, and (c)
recognize when a single device cannot satisfy the intent and walk the user
through building the multiple devices it does require.

## Two kinds of knowledge

The catalog/recommender work buys *syntactic* knowledge -- what configuration is
valid (platforms, fields, types, which `on_*` keys exist). That is importable
from ESPHome's schema and is the easy half.

The hard half is *functional* knowledge -- what each piece **does** and how
pieces **compose** into a behavior. Raw schema does not carry this: it says
`binary_sensor.gpio` has an `on_press` key taking an action list; it does not
say "a button is an input that emits press events you hang actions on." That
functional layer is what lets the model select and connect, and it is the core
of this work.

## The functional/capability layer

Annotate every library component (and, by derivation, every ESPHome platform)
with four things:

1. **Role** -- input event source / sensor value source / output actuator /
   controller. ("Motion detector" -> binary_sensor input, device_class motion;
   "dimmable light" -> PWM output under a `light` platform.)
2. **`provides`** -- events and values the entity emits. Button: press / release
   / click. Encoder: rotation events + a cumulative value. Temp sensor: a float.
3. **`accepts`** -- actions and state the entity takes. Light/switch: turn_on /
   off / toggle. Stepper: set_target. Number: set-value.
4. **Composition grammar** -- the small, finite set of ways ESPHome links
   behavior. Most intent reduces to combinations of five:
   - event -> action
   - value -> transform -> action (the lambda case)
   - state-condition gating (`if` / `condition`)
   - periodic (`interval`)
   - stateful glue (`global` to remember, `script` to reuse)

Provenance: trigger/action *names* and argument shapes come from ESPHome's
schema (import-for-vocabulary, honoring "schema-derived data only, no vendoring
upstream source"). Role and provides/accepts *semantics* need a thin curated
annotation pass on the library, with derivation where the schema makes it
inferable. This annotation + the grammar is the actual deliverable.

Proposed library shape (per component YAML), additive and optional:

```yaml
capability:
  role: input            # input | sensor | output | controller
  provides:
    - {event: on_press,   kind: event}
    - {event: on_release, kind: event}
  accepts: []            # an input typically accepts nothing
```

```yaml
capability:
  role: output
  provides: []
  accepts:
    - {action: turn_on,  esphome: switch.turn_on}
    - {action: turn_off, esphome: switch.turn_off}
    - {action: toggle,   esphome: switch.toggle}
```

## The behavioral graph in design.json

`design.json` stays the single source of truth. Add a first-class, optional
`automations` list -- the behavioral graph, parallel to the existing physical
graph (connections + buses):

```jsonc
"automations": [
  {
    "id": "btn_toggles_light",
    "trigger": {"component_id": "porch_button", "event": "on_press"},
    "conditions": [],
    "actions": [
      {"component_id": "porch_light", "action": "toggle"}
    ]
  }
]
```

For the computed cases the action carries a `transform` (a typed expression the
generator lowers to a `!lambda`), so the value-mapping recipe is reviewed code,
not free-handed YAML. Lowering is a pure function of `design.json` + the
capability annotations -- same contract as every other generator. The agent's
job is intent -> automation structure; the generator owns the YAML.

Two worked examples to validate the schema (built first):
`button_toggles_light` (event -> action) and `encoder_drives_stepper`
(value -> transform -> action).

## Connecting them: two graphs over the same parts

- **Physical graph** -- pins, buses, power. Already built (`set_connection`,
  `add_bus`, `solve_pins`).
- **Behavioral graph** -- connect one component's `provides` to another's
  `accepts`, optionally through a transform. New.

The model's job reads cleanly: **intent -> required roles -> components that
fill those roles -> wire both graphs.** This generalizes past enumerated
templates because it reasons over roles/provides/accepts, not string matches.

## When one device is not enough (topology)

Some intent is inherently distributed: "push a button in this room, have a thing
happen in another room." The input and the output live on different physical
nodes, so it cannot be one `design.json`. The model must:

1. **Detect** -- the requested input role and output role cannot share a board
   (different locations, or a count/placement the user states). This is a
   topology check, distinct from "this board lacks a free pin."
2. **Explain** -- tell the user plainly: this needs N devices, here is what each
   does, and the link between them rides the network, not a wire. Surface the
   transport tradeoff (below) rather than silently picking one.
3. **Walk through** -- create each device design in turn (reusing single-device
   synthesis), then wire the cross-device link, then summarize what lives where.

### The ESPHome boundary

Cross-device behavior is **not** an ESPHome automation -- ESPHome automations
are intra-device. Across devices the connective tissue is one of:

- **Home Assistant (default).** Device A exposes the button as an entity over
  the `api:` (already emitted in the base config); an HA automation turns on
  device B. The link lives in HA, not in either ESPHome YAML -- so the
  deliverable is two device YAMLs **plus** an HA automation we surface (and can
  optionally emit as a YAML snippet the user pastes into HA).
- **Device-to-device native.** ESPHome's `homeassistant` sensor platform (B
  subscribes to an HA entity), `api` services, or MQTT -- still HA/broker-
  mediated but expressible largely in ESPHome YAML.
- **ESP-NOW.** Direct node-to-node, no HA/broker. Lowest latency, no
  infrastructure, but its own setup and no HA visibility.

The agent must understand that "make X in room A do Y in room B" usually implies
Home Assistant (or a broker) as a required component of the *system*, and say so
-- this is exactly the "a single device may not accomplish the intent" case the
user must be told about up front.

### System/topology model

Proposed: a lightweight `system` concept that groups device designs and declares
the links between them. Two options to decide between:

- **A -- explicit system object.** A new `system.json` referencing member design
  ids and a `links: [{from: {design, component, event}, to: {design, component,
  action}, transport: ha|mqtt|espnow}]` list. Clean, inspectable, but a new
  top-level artifact beyond `design.json`.
- **B -- links as design metadata.** Keep designs independent; each carries a
  `peer_links` block referencing the peer design id + transport. No new artifact,
  but the system view is reconstructed by scanning designs.

Recommendation: **A**, because the cross-device link is a relationship that
belongs to neither device alone, and a system object gives the agent a place to
reason about and the UI a place to show the whole topology. Flagging as a
decision to lock -- B is viable if we want to avoid a second artifact type.

## How the agent acquires and uses the knowledge

- **Schema import** -- ESPHome's generated schema as both an MCP *resource* the
  agent can query ("what triggers does this platform expose? what args does
  `stepper.set_target` take?") and the structural validator.
- **Capability annotations** -- the role/provides/accepts function layer on the
  library (above).
- **Composition grammar + topology rules** -- distilled authoring guidance in
  the tool/system prompt: how to wire provides->accepts, when a transform is
  needed, and the single-vs-multi-device decision with its transport tradeoffs.
- **Correctness backstop -- a validation loop, not a constrained vocabulary.**
  Two stages: cheap structural validation against the imported schema (trigger
  exists on platform? action args valid? referenced `component_id` resolves?),
  then the authoritative `esphome config` check already run by
  `scripts/check_examples.py` + the esphome-config workflow. The leverage is
  putting that compile step *inside the agent's authoring loop* so it
  self-corrects before output reaches the user. Open authoring is made safe by
  *checking* the result, not by limiting what the agent can say.

## MCP / agent surface additions

- `query_capability(component_id | platform)` -- read-only; returns role /
  provides / accepts. Lets the agent reason instead of guess.
- `add_automation` / `remove_automation` -- author the behavioral graph
  (validated against capability annotations).
- `suggest_topology(intent)` / `link_devices(...)` -- detect the multi-device
  case and create the system + links.
- Session changes: the active-design model extends to a *system* context so a
  single walkthrough can create and switch between multiple device designs.

## Architecture fit and constraints

- `design.json` stays the single source of truth; generators stay pure
  functions of `design.json` (+ system.json) + library + schema-derived data.
- Schema-derived data only; no vendored upstream ESPHome source.
- Secrets never enter `design.json` / `system.json` -- HA/MQTT credentials stay
  referenced via fleet-for-esphome's `secrets.yaml`.
- Permissive mode: an unsatisfiable or partially-wired automation surfaces in
  `warnings[]`, it does not block generation.
- No premature abstraction: build `button_toggles_light` and
  `encoder_drives_stepper` against the real schema first; generalize the grammar
  only as a third and fourth case demand it.

## Decisions to lock before scoping

1. System topology model: **A (system object)** vs **B (link metadata)**.
2. Cross-device default transport surfaced first: Home Assistant (recommended)
   vs MQTT vs ESP-NOW -- and whether we *emit* the HA automation snippet or only
   describe it.
3. Does the agent get a live `esphome config` check *in its authoring loop*
   (required for safe open-ended intent), or does generation stay deterministic
   with the IR as the ceiling on expressible behavior?
4. Capability annotation: hand-authored on the library now, or blocked on the
   ESPHome schema importer landing first.

## Suggested phasing

1. Capability annotations + `automations` schema + deterministic lowering +
   the two worked examples, gated by `esphome config`. (Single-device behavior.)
2. ESPHome schema import as MCP resource + structural validator; the agent
   authoring loop.
3. System/topology model + cross-device links + the detect/explain/walkthrough
   flow.
