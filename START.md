# esphome-studio — Working State

Living planning doc. Captures vision, decisions, schemas, and phase plan.
For day-to-day work tracking we'll spin off GitHub issues once a phase is
in flight; this doc stays as the strategic reference and decision log.

## Resuming a session

The repo on `main` is the source of truth — every shipped phase is
committed and pushed. To pick up where we left off:

1. Read this `Status` block + `Phasing` below to confirm what's done.
2. Check the **Next up** subsection for the agreed-upon next iteration.
3. Glance at recent commits (`git log --oneline -20`) for the texture of
   what shipped most recently. Each phase has a multi-line commit message
   that's effectively a per-phase changelog.
4. `pip install -e .[dev] && cd web && npm install` to get a working
   tree; `python -m pytest -q` and `cd web && npm test` should be green.

**Last shipped:** streaming agent responses + recommendation mode.
Adds `POST /agent/stream` (SSE) emitting `text_delta`, `tool_use_start`,
`tool_result`, `turn_complete` events; `POST /library/recommend` for
deterministic component ranking; `recommend` agent tool. AgentSidebar
consumes the SSE stream so text and tool calls land live with running/
ok/failed status per tool. The non-streaming `POST /agent/turn` endpoint
stays as a back-compat wrapper. Pytest +21 (179 total), vitest 49, ruff
+ build clean.

**Next up candidates:**
- 0.8 v2 — Thingiverse / Printables search relay. Pulls
  community-uploaded models that already fit the chosen board, ranks
  them, and surfaces the top hits in the same dialog as the
  generator. Thingiverse has a documented API (key + rate limits);
  Printables needs scraping or unofficial endpoints. `httpx.MockTransport`
  for tests, same pattern as the fleet client.
- 0.9 — KiCad schematic export. Full scope in the Roadmap section
  below; key points: SKiDL-driven, `kicad:` reference block per
  component/board (we stay canonical for ESPHome semantics, KiCad
  for schematic rendering), `studio/kicad/scaffold.py` helper for
  cheap library expansion, PCB deferred to 1.0+.

**0.8 v1 -- parametric OpenSCAD enclosure generator shipped.** Each
of the 5 dev-board YAMLs (`wemos-d1-mini`, `esp32-devkitc-v4`,
`nodemcu-32s`, `nodemcu-v2`, `ttgo-lora32-v1`) gains an `enclosure:`
block carrying PCB outline (length / width / thickness in mm), mount
hole positions + diameters, and port cutouts (USB micro on every
board, plus the SMA jack on the TTGO LoRa32 V1). ESP-01S deliberately
skips the block -- it's a header-mount module without a clear PCB
outline.

`studio/enclosure/openscad.py` walks a design's board metadata and
emits a self-contained `.scad` file: tunables block at the top
(wall, floor, clearance, standoff geometry, port_clearance) so the
user can dial in fit without re-rendering, then a `module shell()`
that subtracts an inner cavity + every defined port cutout from the
outer hull, then a `module standoffs()` that places M2.5-clearance
posts at each mount hole. Boards without enclosure metadata raise
`EnclosureUnavailable` cleanly.

`POST /design/enclosure/openscad` returns the text with a
`Content-Disposition: attachment; filename="<design_id>.scad"`
header. Header gains a **Generate enclosure** button that synthesises
the request from the live design and triggers a browser download.

10 new pytest cases pin the renderer (tunables present, dimensions
appear verbatim, mount holes / ports render on the right walls,
short_a vs short_b cutouts translate correctly, ESP-01S fallback);
3 new API tests cover the endpoint contract.

**Drag-and-drop pinout shipped.** New `PinoutView` component renders
a two-column view in the component-instance inspector: left lists
every board GPIO with capability badges (boot strap, ADC1/ADC2,
input-only, serial console, I2C SDA/SCL); right lists this instance's
gpio-target connections as draggable chips. Dropping a chip onto a
board pin rewrites the connection's target. Conflict detection paints
the rose tone on pins another component already uses; the row that's
currently bound (on this instance) glows emerald with a "← <role>"
breadcrumb.

The Connections section gains a Form/Pinout toggle: Form (default)
covers every target kind including the new component target; Pinout
is the visual shortcut for board-pin-heavy designs. Native HTML5
drag/drop -- no library dependency, ~200 lines of TSX, ~150 lines of
test coverage. 7 new vitest cases (empty states, capability badge
rendering, pin-currently-here annotation, conflict detection, the
drag-start-then-drop round trip, and the empty-payload no-op).

**ADS1115 hub-only split shipped.** New `kind: "component"` connection
target lets one component instance reference another by id. The
generator surfaces the referenced instance as `parent` in the
template's Jinja context (sibling to `bus`); the pin solver fills
unbound `kind: component` targets by picking the first design
component whose library_id matches the role's `parent_library_id`
hint on the library Pin. ConnectionForm gains a `component` option
in the kind dropdown with a sibling-instance picker.

`ads1115` is now hub-only -- it registers the `ads1115:` block but
emits no sensors. Each logical reading is a separate
`ads1115_channel` instance with its own multiplexer/gain/update_interval
params and a HUB connection (kind=component) pointing at the hub.
Channels show up as first-class components in the inspector instead
of being buried inside a `channels` array param. The schema /
model / generator / solver / web type extension is generic; future
hub patterns (RGB controllers, multiplexed mux chips) can reuse it
without further surgery.

**SSE log relay shipped.** New `GET /fleet/jobs/{run_id}/log/stream`
endpoint server-side-polls the addon's `/ui/api/jobs/{id}/log` at
~300ms (vs the browser-driven 1.5s) and emits Server-Sent Events:
`data:` frames carry `{log, offset, finished}` chunks; an
`event: done` frame caps a successful run; an `event: error` frame
surfaces logical failures (unknown run_id) so the client knows not
to retry. `interval_ms` query param tunes the cadence with a 100ms
floor.

PushToFleetDialog tries `EventSource` first; on transport error it
closes and falls back to the existing 1.5s `setTimeout` polling
loop, picking up at the offset of the last accepted chunk so no log
bytes are lost. The status pill shows `(stream)` or `(poll)` so
testers can see which path is in use. EventSource isn't on jsdom by
default, so the existing polling tests stay green; the SSE path got
3 new tests using a FakeEventSource stub (chunk -> done flow,
transport-error fallback to polling, server-emitted error event).

241 pytest (+3), 108 vitest (+3), ruff + tsc + vite build clean.

**Library expansion v3 shipped (5 components).**
- `bmp180` — older Bosch barometric T/P (I2C, fixed 0x77, no humidity).
  Renders the deprecated-but-supported `bmp085` ESPHome platform; covers
  legacy modules people still have on hand.
- `htu21d` — T/H (I2C, fixed 0x40). Drop-in for designs that don't need
  pressure; covers the Si7021 / SHT2x families on the same protocol.
- `max31855` — K-type thermocouple amp (SPI, MISO-only). Range -270 to
  +1372°C. Optional `reference_temperature: true` publishes the cold-
  junction reading. CS is per-component native (`spi_cs`).
- `hx711` — 24-bit load-cell ADC, custom 2-wire serial (DOUT + SCK on
  free GPIOs, no bus). Channel A 128/64x or channel B 32x via the
  `gain` param.
- `tsl2561` — ambient light / lux (I2C). Address selectable across
  0x29/0x39/0x49 via the ADDR pin; gain + integration_time tunables.

10 new tests: 5 yaml-gen smoke (each component renders the expected
ESPHome platform with the right pin / address / param wiring) + 5
recommender pin tests (thermocouple, weight, lux, pressure, humidity
all land on the right top pick).

**Library expansion: ADS1115 + MPU6050 shipped.**
- `library/components/ads1115.yaml`: 4-channel 16-bit ADC over I2C.
  Renders an `ads1115:` hub block + per-channel `sensor:` entries
  driven by a `channels` param (multiplexer, name, gain, update_
  interval). Address selectable via the ADDR pin maps to 0x48-0x4B.
  Solves the ADC2/WiFi conflict on classic ESP32 by giving the
  chip a known-good external ADC.
- `library/components/mpu6050.yaml`: 6-axis IMU (3-axis accel +
  3-axis gyro + die temp). All seven channels emitted in one
  `sensor:` entry; AD0 selects 0x68/0x69. The INT pin isn't modeled
  yet -- a binary_sensor in esphome_extras handles motion-wake until
  someone needs richer support.
- 4 new yaml-gen tests (per-channel rendering, hub-with-no-channels
  smoke, full IMU axis emission, both parts sharing a single I2C
  bus) + 2 new recommender tests (adc query lands on ads1115, IMU
  queries land on mpu6050).

**Inspector composition tests shipped.** New `Inspector.test.tsx`
(9 tests) covers the DesignInspector composition: null-design
fallback, component row rendering with id+label+library_id, section
counts (Components/Buses/Requirements/Warnings) reflecting the design,
selection callback firing with `kind: "component_instance"` when a
row is clicked, the per-row ✕ wiring through to onRemoveComponent,
the Compatibility section's hide/show on warning presence, the Fleet
section's gate on the design's fleet block, and the empty-components
affordance. api.getComponent is mocked at the boundary; no real
network calls.

228 pytest (+6), 105 vitest (+9), ruff + tsc + vite build clean.

**1-wire bus type promotion shipped.** The `Bus` model gains a `pin`
field (single-pin bus, parallel to the multi-pin sets on i2c/spi).
yaml_gen renders a top-level `one_wire:` block per 1-wire bus
(`{platform: gpio, pin, id}`) so multiple sensors on a shared physical
bus emit a single bus block, not one per sensor. The DS18B20 template
no longer carries a `one_wire:` block of its own -- it reads `bus.id`
and emits `dallas_temp` with the matching `one_wire_id`. Pin-solver
and bus-pin compatibility checks gain a `1wire` entry; the BusList
editor surfaces a `pin` field on 1wire cards instead of the previous
"lives on each component" placeholder. design.ts's `neededBusTypes`
and `defaultTargetForPin` recognise the new `onewire_data` pin kind.

New `examples/multi-temp.json` + golden artifacts pin the round-trip:
two DS18B20s with distinct ROM addresses sharing `wire0` on D6 plus
an RCWL-0516 microwave motion sensor on D5. 4 new pytest cases (2
yaml-gen, 1 ascii-gen golden, 1 yaml-gen single-instance smoke).

**Strict-only push gate shipped.** `POST /fleet/push` now accepts
`strict: bool` and refuses the push with the same `strict_mode_blocked`
envelope that `/design/render?strict=true` uses when any warn/error
compat entry remains. The studio app threads its global strict-mode
toggle into `PushToFleetDialog` as a prop; the dialog renders an
amber notice when strict is on and the result-banner formatter
recognises the envelope so the user sees the friendly message
instead of the raw JSON. 2 new pytest cases pin the gate.

**Library expansion: RCWL-0516 + DS18B20 shipped.**
- `library/components/rcwl-0516.yaml`: microwave doppler motion sensor.
  Same VCC/GND/OUT pin set as the HC-SR501 PIR but draws ~3 mA peak
  vs ~50 mA, so it complements the PIR for battery builds. No params
  (sensitivity/on-time live on the SMD resistors). Recommender ranks
  it alongside the PIR for `motion`/`occupancy`/`presence` queries.
- `library/components/ds18b20.yaml`: first 1-wire library citizen.
  VCC/GND/DATA + the canonical 4.7kΩ pull-up between DATA and VCC
  encoded in `passives`. Each instance renders its own
  `one_wire: [{ id: <comp>_bus }]` block plus a `dallas_temp` sensor
  pointing at it; the existing `_deep_merge` of list-typed top-level
  blocks means N independent DS18B20s on N different pins coexist
  cleanly. Sharing a single physical bus among multiple sensors is
  noted in the component's `notes` field but not yet wired -- that's
  a 1-wire-bus promotion candidate above. Params expose `address`
  (ROM), `update_interval`, `resolution` (9-12 bits).

7 new pytest cases (yaml gen for both + recommender ranks both +
strict push). 220 pytest, 96 vitest, ruff + tsc + build clean.

**ConnectionForm + PushToFleetDialog component tests shipped.** New
`ConnectionForm.test.tsx` (7 tests) covers the LockToggle's three
states (unlocked / locked-in-sync / locked-diverged), the disabled
state when no pin is bound, the onLockedPinChange round-trip, the
inline mismatch hint, and the non-render guard for non-gpio targets.
New `PushToFleetDialog.test.tsx` (6 tests) covers the status fetch
gating Push, the device-name round-trip in the fleetPush payload,
no-run_id-no-log-viewer, single-shot finished-on-first-poll, and
`vi.useFakeTimers` driven multi-chunk polling that confirms the
1.5s gap is honoured and the second poll fetches at the offset
returned by the first. Plus an error-path test that surfaces
"log error: addon disconnected" and stops the loop.

**Strict-mode toggle shipped.** `POST /design/render?strict=true`
now refuses to produce YAML/ASCII when any compatibility entry of
severity warn or error remains; the response is a 422 with detail
shape `{error: "strict_mode_blocked", message, warnings[]}`. Header
gains a "strict" checkbox (amber-tinted when on, plain when off);
flipping it re-fires the debounced render with the new flag in the
deps array. The existing renderError banner gets a small upgrade to
recognise the `strict_mode_blocked` envelope and surface the count
instead of dumping the JSON envelope. info-severity entries are
deliberately left as a permissive signal -- they're educational
(voltage_limit on D1 Mini A0, current-budget guidance) and don't
block. 3 new pytest cases pin the gate.

**Capability picker alternatives disclosure shipped.** Each match in
the picker now carries a small "▸ N alternatives" toggle below its
metadata row. Clicking expands an inline list of the OTHER currently-
visible matches (filtered through the same bus filter) with their
score and the delta against the row -- emerald-tinted when an
alternative beats the row's score, muted-zinc when it's worse.
Single-expanded-at-a-time policy: opening one closes the previous so
the result list never grows multiple stacked alternatives panels.

**RTL/jsdom component tests scaffolded.** New `vitest.config.ts`
extends the existing vite config with `environment: "jsdom"` and a
setup file that imports `@testing-library/jest-dom` matchers. First
two suites cover the surfaces with the most state machinery:
- `BusList.test.tsx`: rename draft commits on Enter, reverts on
  Escape (caught and fixed a real bug -- the previous Escape handler
  blurred the input, racing the queued state reset and leaking the
  stale draft through commitRename), rejects collision with another
  bus's id, inline compat warnings filter to the matching card.
- `CapabilityPickerDialog.test.tsx`: alternatives disclosure shows
  "N alternatives" toggle on every multi-match list, expansion is
  single-row-at-a-time with aria-expanded synchronised, score delta
  carries the sign and the right tint, bus filter hides + counter
  surface and the unhide path. Plus an Add round-trip that confirms
  onAdd receives the library_id and the row flips to the affirmation.

15 new vitest cases (53 -> 68 -> 83); the network surface is mocked
at the api/client boundary so the suite stays fast (2.4s for all 83).

**Bus rename propagation + inline bus card warnings shipped.** New
`renameBus(d, oldId, newId)` helper rewrites the bus's id and every
`connection.target.bus_id == oldId` atomically. The bus card's id
input now keeps a local draft and commits on blur or Enter (Esc
reverts) so a mid-typing intermediate like "" or "i" doesn't briefly
orphan connections; the field tints amber while dirty and red on a
collision with another bus's id. `updateBus` silently strips an `id`
key from its patch so nothing else sneaks past renameBus. Each bus
card now also filters whole-design compatibility warnings down to
its own (matched on `component_id`) and renders them inline below
the pin grid in severity-tinted rows -- so a boot-strap warning on
`spi0.CLK` shows up on the spi0 card, not just under the design's
Compatibility section.

**Pin-lock inspector toggle shipped.** Connection rows in the inspector
gain a 🔓/🔒 button next to the gpio pin selector. Click 🔓 lock to
write `locked_pins[role]` for the currently bound pin; click 🔒 to
clear it. The lock badge turns amber when the bound pin diverges from
the lock and an inline "solver will flag a mismatch" hint surfaces
the discrepancy without leaving the row. Reads/writes go through new
`readConnections.locked_pin` and `setLockedPin` helpers in
`web/src/lib/design.ts`.

**Bus editor shipped.** Design Inspector now has a Buses section with
one card per bus. Each card lets the user rename the id, edit the
type's pin slots (`sda`/`scl` for i2c, `clk`/`miso`/`mosi` for spi,
`tx`/`rx` for uart, `lrclk`/`bclk` for i2s) plus the type's tunable
(frequency_hz / baud_rate). Pin selectors are populated from the
board's `gpio_capabilities`; an "+ add bus" picker creates a fresh bus
seeded from `board.default_buses` when present. Removing a bus
intentionally leaves connections that target it dangling so the
render-time error makes the inconsistency loud.

**Pin locks shipped (permissive).** `Component.locked_pins` is no
longer dead code:
- Solver applies locks before solving. Empty gpio targets get filled
  from the lock; bound targets that disagree surface a
  `locked_pin_mismatch` warning (the bound pin stays put — divergence
  might be intentional). Lock keys that aren't real roles on the
  library component surface a `locked_pin_unknown_role` warning.
  Locks against non-gpio targets surface `locked_pin_wrong_kind`.
- compatibility.py validates the lock's target pin against the role's
  required capability; a `locked_pin_invalid` (severity: error) fires
  when, say, an `analog_in` lock lands on a pin without `adc`.
- 6 new tests pin all paths.

**Capability picker bus filter shipped.** Dialog now receives the
design's bus types (i2c/spi/uart/i2s/1wire) and offers a "match my
buses" checkbox (default on). When on, ranked matches whose
`required_components` include a bus the design lacks are dropped
from the visible list with a "N hidden by the bus filter" note.
Uncheck to see everything (e.g., when the user is happy to add a
new bus). The agent's recommend tool is unchanged — this is a
UI-side filter only.

**Capability-driven "Add by function" picker shipped.** New backend
endpoint `GET /library/use_cases` aggregates the library's canonical
capability vocabulary (sorted by component count, with a 3-id sample
per row). Header button **Add by function** opens a two-pane dialog:
left shows the use_case rows + a free-text override; right runs the
existing `/library/recommend` and renders ranked matches with rationale,
current draw, voltage range, and a one-click Add button that reuses the
same `handleAddComponent` path as the inspector. The first result is
badged "top pick" but the user can grab any of the eight returned —
the case where you already have a specific part on hand.

**0.7+ build-log polling shipped.** Studio relays the addon's HTTP
fallback `GET /ui/api/jobs/{id}/log?offset=N` as `GET /fleet/jobs/{run_id}/log`
and the Push-to-fleet dialog tails it (1.5s poll) into a scrolling
viewer below the result banner once a compile is enqueued. 6 new fleet
tests cover unconfigured 503, unknown run_id 502, and the offset-based
chunking contract.

**ADC2/WiFi conflict detection shipped.** All three ESP32 boards
(esp32-devkitc-v4, nodemcu-32s, ttgo-lora32-v1) carry `adc1` / `adc2`
pin tags. compatibility.py emits `adc2_wifi_conflict` warnings when an
analog_in lands on an ADC2 pin on a classic ESP32 (chip_variant ==
"esp32"); the pin solver uses a secondary preference key so unbound
analog_in connections land on ADC1 pins (GPIO32-39) by default. 4
new tests pin both paths.

**0.7 distributed-esphome handoff shipped.** `studio/fleet/client.py`
talks to the ha-addon's `/ui/api/*` surface using a Bearer token.
`GET /fleet/status` + `POST /fleet/push` expose this to the UI;
**Push to fleet** in the header opens a modal with the device-name
input, a status banner, and a "compile after upload" toggle. Config:
`FLEET_URL` + `FLEET_TOKEN` env vars on the API server. Tests use
`httpx.MockTransport` to stand in for the addon -- 18 new tests
covering filename validation, configured-vs-unauthorized status,
pending-rename create flow, in-place overwrite, compile enqueue,
and the HTTP contract end-to-end.

## Status (as of 2026-05-04)

- **0.1 MVP shipped.** `python -m studio.generate examples/<name>.json`
  produces ESPHome YAML + ASCII diagrams pinned by goldens.
- **0.2 HTTP API shipped.** FastAPI server at `python -m studio.api`,
  endpoints under `/library/*`, `/design/*`, `/examples/*`. Auto-generated
  OpenAPI docs at `/docs`. Pure layer over the generators, no server-side
  state. Permissive CORS for the 0.3 web UI.
- **0.3 web UI v1 shipped.** React 19 + Vite + Tailwind v4 under `web/`.
  Three-pane layout (examples/library sidebar / design preview /
  inspector). Editable surfaces:
  - **design view**: board picker (dropdown of all library boards),
    fleet metadata (device_name + tags), requirements list (add /
    edit / remove), warnings list (add / edit / remove);
  - **component-instance view**: params (form generated from the
    library's `params_schema`), connections (per-row editor with
    target-kind selector and rail/gpio/bus/expander_pin sub-controls).
  Add/remove component instances from the components list (with
  auto-wiring: rails picked by voltage match, bus pins linked to a
  matching bus, missing buses auto-prepended from the board's
  `default_buses`). Edits land in local design state and re-render via
  debounced (250ms) `POST /design/render`. Reset reverts to the loaded
  example; Download JSON saves the modified design.json. Vitest covers
  `lib/design.ts` (41 tests). Drag-and-drop pinout and bus editor
  are follow-on iterations.
- **0.4 USB device bootstrap shipped.** "Connect device" header button
  opens a modal that runs `esptool-js` over WebSerial. Reads chip
  family + MAC, normalizes the chip name (ESP32-S3 -> esp32s3),
  filters the board library to candidates with the matching
  `chip_variant`, and on adopt seeds a fresh `design.json` with the
  picked board pre-filled and an `info` warning carrying the
  detected chip + MAC. esptool-js is dynamic-imported so vitest
  (no `navigator.serial`) doesn't choke; Vite code-splits the
  per-chip stub flashers into separate chunks loaded only on demand.
  WebSerial is Chromium-only so a fallback notice steers
  Firefox/Safari users to the manual flow. Vitest +8 tests
  (49 total) cover chip-name normalization, board candidate
  matching, and bootstrap-design shape.
- **0.5 agent layer shipped.** Claude tool-using agent at
  `studio/agent/` (`tools.py`, `session.py`, `agent.py`). 10-tool
  surface: `search_components`, `list_boards`, `set_board`,
  `add_component`, `remove_component`, `set_param`, `set_connection`,
  `add_bus`, `render`, `validate`. Manual agentic loop on
  `claude-opus-4-7` with adaptive thinking; library JSON cached in the
  system prompt for ~90% read discount on subsequent turns; per-turn
  design context goes in the user message so the cache stays valid as
  the design changes. Conversation history persists in
  `sessions/<id>.jsonl` (plain role/text only; the tool ceremony stays
  in memory). API: `POST /agent/turn` returns updated design +
  assistant text + a tool-calls log; `GET /agent/status` reports
  availability; `GET /agent/sessions/{id}` returns the JSONL contents.
  Agent endpoints 503 cleanly when `ANTHROPIC_API_KEY` is unset. Web
  UI: header `Agent` button opens a sidebar drawer; chat replaces the
  working design on each turn so the live YAML/ASCII updates as the
  agent edits. Pytest +24 (114 total) covers every tool implementation,
  session JSONL round-trip, and the API contract (status / 503 / 404).
- **0.6 CSP solver + port compatibility validation shipped.** Pin
  solver at `studio/csp/pin_solver.py`. Port compatibility validator at
  `studio/csp/compatibility.py` walks every gpio + bus pin assignment
  and emits codes (`input_only_as_output`, `boot_strap_output`,
  `serial_console`, `voltage_limit`, `function_unsupported`) based on
  the board YAML's semantic tags (`boot_high`, `boot_low`, `serial_tx`,
  `serial_rx`, `pull_up_external`, `pull_down_external`, `adc_max_1v`,
  `no_pwm`, `no_i2c`, `no_interrupt`, `no_pull_internal`). Auto-runs
  on every `/design/render`, `/design/validate`, and
  `/design/solve_pins`; surfaces in the Inspector's design view as a
  Compatibility section, plus filtered to per-instance in the
  component-instance view. Solver also deprioritizes boot-strap and
  serial pins for output assignments. Pytest +14 (138 total) covers
  every code path including a known-examples snapshot test that
  catches regressions in the board YAML tags.

- **legacy 0.6 entry below kept for context.** `studio/csp/pin_solver.py` -- pure
  Python, no external solver lib (problem size is tiny). Fills every
  unbound connection: `kind: gpio` with empty pin -> a board GPIO
  matching the library pin's capability (digital in/out -> any gpio,
  analog_in -> needs `adc`, with strap/boot/builtin_led pins
  deprioritized for outputs); `kind: bus` with empty bus_id -> first
  matching design bus, with a "no_matching_bus" warning when the type
  is missing; `kind: expander_pin` with empty expander_id -> next free
  slot on the first io_expander. Already-bound pins are left alone
  (the user's call) but conflicts surface as warnings. Current budget
  is checked: peak draw > `power.budget_ma` emits a `current_budget`
  warning. Pure: returns a new design dict alongside the diff and any
  warnings. Wired in three places: a `solve_pins` agent tool (the
  agent uses it after a non-trivial wiring change), a standalone
  `POST /design/solve_pins` HTTP endpoint, and a `Solve pins` header
  button in the web UI that shows a transient banner with the
  assignments + warnings. Pytest +12 (126 total) covers the
  no-mutation invariant, gpio/bus/expander assignment, no-candidate
  paths, conflict + budget warnings, and the "no board"/"unknown
  board" error paths.
- **12 example designs** spanning ESP8266 + ESP32 + ESP-IDF + Sonoff:
  garage-motion, awning-control, wasserpir, oled, bluemotion,
  distance-sensor, securitypanel, rc522, esp32-audio, bluesonoff,
  wemosgps, ttgo-lora32.
- **Library:** 6 boards, 14 components, 5 bus types (i2c/spi/uart/1wire/i2s),
  4 connection target kinds (rail/gpio/bus/expander_pin).
- **Tests:** 89 passing (CLI generators + API), ruff clean.
- **Decided:** option 1 (`kind: expander_pin`) for expander wiring;
  shipped. UI-first phasing: API → Web UI → USB bootstrap → Agent → CSP.

## Vision

Agent-driven ESPHome device design tool. User describes a goal (or picks parts);
tool produces an ESPHome YAML, an ASCII wiring diagram, a BOM, and (later) hands
the device off to `weirded/distributed-esphome` for compile + OTA deploy.

Sister project to `weirded/distributed-esphome`. Knowledge base seeded from
`esphome/esphome` (schemas) plus a hand-curated electrical library.

## Decisions locked

- **Repo:** `moellere/esphome-studio` (new, just created).
- **Mode:** **Permissive.** CSP/electrical violations surface as `warnings[]`,
  do not block generation. Revisit for "strict mode" toggle later.
- **Wiring output for 0.1:** **ASCII art only.** KiCad deferred (still the
  longer-term target — design model must not paint into an ASCII corner).
- **Stack:** Python backend (FastAPI or aiohttp — match distributed-esphome),
  React 19 + Vite + Tailwind + shadcn frontend (later), Claude API for the
  agent (with prompt caching for the component KB).
- **Single source of truth:** `design.json` (versioned, JSON-Schema-validated).
  All artifacts (YAML, ASCII, BOM) are derived. No round-trip from artifacts
  back to the document.
- **Conversation/document split:** Agent chat history stored separately
  (`sessions/<id>.jsonl`). `design.json` stays clean and diff-able.
- **Reasoning layers:**
  1. Agent (Claude, tool-using) — elicitation, recommendations, narrative.
  2. CSP solver (`python-constraint` or OR-tools) — pin/bus/budget assignment.
  3. Generators (pure functions) — `design.json` → YAML / ASCII / BOM.
- **Secrets:** Never in `design.json`. Reference `distributed-esphome`'s
  `secrets.yaml` via `!secret name`.
- **Knowledge base sources** (see *Library sourcing strategy* below for the
  hybrid plan): ESPHome integrations for YAML schema, PlatformIO board JSON
  for board metadata, hand-curation + LLM-extracted datasheet data for the
  electrical layer ESPHome doesn't carry.

## Phasing

UI-first ordering: a manual web UI ships before the agent so users have an
immediate way in and the agent (when it arrives) lands in a working surface.

- **0.1 — MVP pipeline.** ✅ Shipped. `design.json` → ESPHome YAML + ASCII.
  Library scaffolding, generators, golden tests.
- **0.2 — HTTP API.** ✅ Shipped. FastAPI server (`python -m studio.api`),
  endpoints under `/library/*`, `/design/*`, `/examples/*`. Auto-generated
  OpenAPI at `/docs`. CORS open for `localhost:5173`/`localhost:3000` so
  0.3's UI can hit it directly. Pure layer over `studio.generate`, no
  server-side state. /design/render currently returns `{yaml, ascii}`;
  structured BOM + power-budget responses will be added when 0.3 needs
  them rather than guessed at now.
- **0.3 — Studio Web UI v1.** React 19 + Vite + Tailwind v4 under `web/`.
  Three-pane layout: left sidebar (examples / boards / components with
  search), center design pane (ASCII / YAML / JSON tabs + design header),
  right inspector (design / board / component / component-instance
  views). Read-only first iteration shipped, then param-edit forms
  layered on: clicking a component instance opens a generated form
  (string / enum / int / bool) populated from `params_schema`; edits
  flow back to local design state and re-render via debounced
  `/design/render`. Connection / bus / board edits, drag-and-drop, and
  the agent sidebar (0.5) are follow-on iterations.
- **0.4 — USB device bootstrap.** ✅ Shipped (initial). "Connect device"
  toolbar button opens a modal that uses
  [`esptool-js`](https://github.com/espressif/esptool-js) over WebSerial
  in the browser to detect chip family + MAC, then offers the matching
  boards from the library. Picking one seeds a fresh `design.json` with
  the board pre-filled. Pure browser, no backend involved. Same approach
  web.esphome.io uses. Future: also detect flash size + PSRAM presence
  for richer board disambiguation, and support specifying a custom
  baud rate / reset strategy for stubborn boards.
- **0.5 — Agent layer.** ✅ Shipped (initial). Claude tool-using agent
  with the constrained tool surface in *Agent tool surface* below.
  Lands as a sidebar in the UI; also exposed via `POST /agent/turn`.
  Conversation history in `sessions/<id>.jsonl`, separate from
  `design.json`. Future: streamed responses (currently waits for
  end_turn before returning), agent-side handoff to 0.6's CSP solver
  via a `solve_pins` tool, recommendation mode ("I want motion
  detection" → ranked options).
- **0.6 — CSP solver.** ✅ Shipped (initial). Pin assignment lives in
  `studio/csp/pin_solver.py`; surfaced as the `solve_pins` agent tool,
  the standalone `POST /design/solve_pins` endpoint, and a "Solve pins"
  header button. Greedy + capability-aware: respects board GPIO
  capabilities, prefers non-strap pins for outputs, picks first
  matching bus by type, fills expander pins on the first io_expander.
  Future: recommendation mode ("I want motion detection" → ranked
  options), strict-mode pin locks, multi-objective optimization
  (minimize used pins, minimize current draw, maximize headroom),
  proper backtracking on hard constraints.
- **0.7 — distributed-esphome handoff.** ✅ Shipped (initial). The studio
  API talks to the ha-addon's `/ui/api/*` surface using `FLEET_URL` +
  `FLEET_TOKEN`. Push uses the addon's staged-create flow (`.pending.<n>.yaml`
  -> `<n>.yaml`) for new devices, in-place writes for existing ones.
  Optional `compile: true` enqueues an OTA build via `POST /ui/api/compile`.
  UI: **Push to fleet** modal with status banner + device-name input.
  Future: live build-log tailing, queue/history surface, fleet-side
  device list to pick a target name from.
- **0.8 — Enclosure suggestions.** Two halves:
  - **v1 ✅ Shipped (parametric OpenSCAD generator).** Each dev-board
    YAML carries an `enclosure:` block with PCB outline + mount holes
    + port cutouts. `studio/enclosure/openscad.py` emits a
    self-contained `.scad` shell (bottom + 4 walls, mounting standoffs
    aligned with the mount holes, edge cutouts for every port) with
    tunables (wall, floor, clearance, standoff geometry) at the top
    so the user dials in fit without re-rendering. Endpoint
    `POST /design/enclosure/openscad`; header **Generate enclosure**
    button triggers a browser download.
  - **v2 — Thingiverse / Printables search relay.** Pull
    community-uploaded models that fit the chosen board + components,
    rank them, and surface the top hits alongside the generator.
    Same `enclosure:` metadata feeds the search query.
  - **Stretch — component dimensions on breakouts** (BME280 module,
    OLED module, etc.) so the generator can place display windows
    and stack-mount cutouts, not just the headline USB port.
- **0.9 — KiCad schematic export.** Walk `design.json` and emit a
  `.kicad_sch` (KiCad 6+ s-expression format) the user opens in
  KiCad. SKiDL is the recommended path: a mature Python DSL that
  takes parts + nets and writes the schematic for us. Concretely:

  - **Library mapping, not duplication.** Our `library/components/<id>.yaml`
    stays the canonical source for ESPHome semantics; it gains a small
    `kicad:` block that *references* the matching `kicad-symbols`
    entry rather than copying its pin geometry. The two libraries
    sit at orthogonal layers -- KiCad's covers schematic rendering
    (pin numbers, electrical types, footprint, datasheet); ours
    covers the rest (Jinja YAML template, use_cases, required buses,
    `params_schema`, electrical bounds, capability tags). Replacing
    one with the other moves the data, doesn't eliminate it.

    Block shape:
    ```yaml
    kicad:
      symbol_lib: Sensor
      symbol: BME280
      footprint: Package_LGA:LGA-8_2.5x2.5mm_P0.65mm_LayoutBorder3x3y
      pin_map:                # studio role -> KiCad pin name
        VCC: VDD
        GND: GND
        SDA: SDA
        SCL: SCL
    ```

    Pin map handles the cases where our role names differ from a
    symbol's (e.g., our `VCC` vs Bosch's `VDD`); most parts are 1:1.

  - **Boards likewise.** `library/boards/<id>.yaml` gains the same
    `kicad:` block (e.g., WeMos D1 Mini -> `MCU_Module:WeMos_D1_mini`),
    so the schematic gets the right module symbol, not just a sea of
    nets.

  - **Generator.** New `studio/kicad/` module: walks `design.json`,
    converts each component instance into a SKiDL `Part(...)`, each
    connection into a Net assignment, and either emits a SKiDL Python
    script (the user runs it themselves) or invokes SKiDL in-process
    to write `<design_id>.kicad_sch` directly. New endpoint
    `POST /design/kicad` returns the artifact; CLI gets a
    `--out-kicad` flag.

  - **Scaffold helper.** Cheap tooling win: `studio/kicad/scaffold.py`
    reads a `.kicad_sym` file and prints a starter
    `library/components/<id>.yaml` skeleton (pin roles + voltage
    hints prefilled from the symbol's pin electrical_types). Cuts
    ~80% of the boilerplate when adding a new library entry. Author
    fills in the ESPHome template + use_cases + params_schema after.

  - **Coverage.** `kicad-symbols` (the libraries shipped with KiCad,
    CC-BY-SA + GPL exception) covers nearly every component we
    already have: BME280, BMP180, HTU21D, DS18B20, MPU6050, ADS1115,
    TSL2561, MAX31855, HX711, SSD1306, MCP23008/17, SX127x, WS2812B,
    plus the board modules. The PIRs (HC-SR501) and microwave radar
    (RCWL-0516) are typically wired as 3-pin `Connector_Generic`
    instances since they're breakouts; same for HC-SR04. SnapEDA /
    Component Search Engine cover the remaining manufacturer parts
    (RC522 etc.) for free.

  - **PCB layout deferred to 1.0+.** SKiDL can also emit netlists
    that feed Freerouting + KiCad's PCB editor, but auto-routed
    boards are a per-design quality concern that wants its own
    iteration. 0.9 ships only the schematic.

- **Future — KiCad PCB layout.** Reuse the schematic's netlist;
  Freerouting for autorouting; Gerber + JLCPCB CPL/BOM export.

The UI-first ordering means 0.5's agent and 0.6's solver each have a
visible place to land. If the agent lands first (alternative ordering),
it ships as a CLI/tool-only surface and we re-skin it later — strictly
worse for the headline feature.

### Next up (queued, not started)

Two small follow-ons to 0.5's agent layer, agreed in the last session:

1. **Streaming agent responses.** Swap `POST /agent/turn` for an SSE
   variant that emits events as they happen:
   `tool_use_start { tool, input }`, `tool_result { tool, is_error }`,
   `text_delta { text }`, then a final `turn_complete { design, usage }`
   carrying the updated design state. Frontend reads the stream and
   updates the chat + tool-call UI live; the design swap happens once
   on the final event so the live YAML/ASCII doesn't churn mid-turn.
   Improves perceived latency a lot — currently a 4-tool turn looks
   like a 5-second blank stare.

   Implementation sketch: keep `/agent/turn` for backward-compat,
   add `POST /agent/stream` (or upgrade `/agent/turn` to also accept
   `Accept: text/event-stream`). Reuse the manual agentic loop in
   `studio/agent/agent.py`; just yield events instead of accumulating.
   Anthropic SDK supports `client.messages.stream(...)` with
   `get_final_message()` — the per-tool-call dispatch stays the same.

2. **Recommendation mode.** New `recommend(query)` agent tool that
   takes a capability query (*"motion detection on a battery-powered
   ESP32"*, *"weather station outdoors"*) and returns ranked component
   candidates with electrical trade-offs. Pairs naturally with the
   solver: pick a candidate, add it, solve. Shape:

   ```python
   {
       "name": "recommend",
       "description": "...",
       "input_schema": {
           "type": "object",
           "properties": {
               "capability": {"type": "string"},
               "constraints": {"type": "object"},  # power, indoor/outdoor, etc.
           },
       },
   }
   ```

   The tool implementation is a small ranking function over
   `library.list_components()`: filter by `use_cases` + `aliases`
   matching the query; rank by current draw, voltage compatibility,
   and presence in existing examples (a proxy for "battle-tested").

   v1 should NOT call out to an LLM internally — keep the recommender
   deterministic and fast. The agent then narrates the options.

Both fit comfortably in one PR. Streaming first (it's the bigger UX
win); recommend second.

## Studio web UI (0.3)

Three-panel layout, all driven by the API in 0.2.

- **Library panel (left).**
  - Search box, category facets (sensor, display, switch, expander, light,
    io_expander, …), bus-type chips (i2c, spi, uart, 1wire, i2s).
  - Two tabs: *Components* and *Boards*.
  - Drag a component card onto the canvas to add to the current design.
- **Design canvas (center).**
  - Top: board pinout diagram with active connections drawn as wires
    between board pins and component blocks. Reuses the `gpio_capabilities`
    map from board YAMLs to color pins by capability.
  - Middle: ASCII diagram block (the current `ascii_gen` output, rendered
    in a monospace box). Live re-render on every design change.
  - Bottom: BOM table + power summary + warnings tray.
- **Inspector panel (right).**
  - When a component is selected: editable form for `params`, derived from
    the component's `params_schema`. Connection list with per-pin assignment.
  - When a connection is selected: kind selector (rail / gpio / bus /
    expander_pin once 0.4-ish); pin picker filtered by capability.
  - When the design root is selected: board picker, power supply, fleet
    metadata, secrets references, requirements list.
- **Toolbar.**
  - "Connect device" (0.4) → triggers WebSerial detect.
  - "Talk to agent" (0.5) → opens agent sidebar.
  - "Solve pins" (0.6) → runs CSP, applies result, shows diff.
  - "Push to fleet" (0.7) → POST to distributed-esphome.
  - Export YAML / Export ASCII / Export `design.json`.

Recommendation surfaces (ranked component options for a stated capability)
fold into the library panel as a separate "Suggest" mode.

## USB device bootstrap (0.4)

Flow:

1. User clicks "Connect device". Browser prompts for serial port permission
   (Chrome WebSerial; no extension or backend needed).
2. `esptool-js` reads chip variant (`esp32`, `esp32s3`, `esp32c3`, `esp8266`,
   `esp8285`, `esp32c6`, etc.), flash size, MAC.
3. Studio cross-references the chip variant against `library/boards/*.yaml`,
   filtering to boards whose `mcu` / `chip_variant` match.
4. UI shows top 3-5 candidates ("ESP32 chip with 4MB flash and PSRAM
   detected — likely candidates: ESP32-DevKitC-V4, ESP32-WROVER-Kit. Pick
   one, or pick *Generic ESP32-WROOM-32*."). User picks.
5. Studio bootstraps a `design.json` with the `board:` block populated and
   an empty `components: []`. `power.budget_ma` defaults from the board's
   regulator metadata.
6. Normal design flow from there. Detected chip is also retained as a
   `warnings[]` entry if the user later changes the board to something
   incompatible with what's actually plugged in.

This is where the studio earns its "agentic but grounded" framing: the
agent never has to *guess* what hardware you have — the device tells us.

## `design.json` (schema_version 0.1)

​```jsonc
{
  "schema_version": "0.1",
  "id": "garage-motion-v1",
  "name": "Garage motion sensor",
  "description": "Outdoor PIR + temp/humidity, USB powered.",
  "created_at": "2026-05-03T12:00:00Z",
  "updated_at": "2026-05-03T12:34:00Z",

  "board": {
    "library_id": "esp32-devkitc-v4",
    "mcu": "esp32",
    "framework": "arduino",
    "pinned_esphome_version": "2024.10.0"
  },

  "power": {
    "supply": "usb-5v",
    "rail_voltage_v": 5.0,
    "regulator": "onboard-ams1117",
    "budget_ma": 500
  },

  "requirements": [
    { "id": "r1", "kind": "capability",  "text": "detect motion at front door" },
    { "id": "r2", "kind": "environment", "text": "outdoor, covered" },
    { "id": "r3", "kind": "constraint",  "text": "USB powered" }
  ],

  "components": [
    {
      "id": "pir1",
      "library_id": "hc-sr501",
      "label": "Driveway PIR",
      "role": "motion_sensor",
      "params": { "retrigger": "H", "pulse_ms": 2500 },
      "locked_pins": {}
    },
    {
      "id": "bme1",
      "library_id": "bme280",
      "label": "Porch climate",
      "params": { "address": "0x76" }
    }
  ],

  "buses": [
    { "id": "i2c0", "type": "i2c", "frequency_hz": 100000,
      "sda": "GPIO21", "scl": "GPIO22" }
  ],

  "connections": [
    { "component_id": "pir1", "pin_role": "VCC", "target": { "kind": "rail", "rail": "5V" } },
    { "component_id": "pir1", "pin_role": "GND", "target": { "kind": "rail", "rail": "GND" } },
    { "component_id": "pir1", "pin_role": "OUT", "target": { "kind": "gpio", "pin": "GPIO13" } },
    { "component_id": "bme1", "pin_role": "VCC", "target": { "kind": "rail", "rail": "3V3" } },
    { "component_id": "bme1", "pin_role": "GND", "target": { "kind": "rail", "rail": "GND" } },
    { "component_id": "bme1", "pin_role": "SDA", "target": { "kind": "bus", "bus_id": "i2c0" } },
    { "component_id": "bme1", "pin_role": "SCL", "target": { "kind": "bus", "bus_id": "i2c0" } }
  ],

  "passives": [
    { "id": "c1", "kind": "capacitor", "value": "100nF",
      "between": ["bme1.VCC", "GND"], "purpose": "decoupling bme1" },
    { "id": "r1", "kind": "resistor",  "value": "4.7k",
      "between": ["i2c0.SDA", "3V3"],  "purpose": "I2C pull-up" },
    { "id": "r2", "kind": "resistor",  "value": "4.7k",
      "between": ["i2c0.SCL", "3V3"],  "purpose": "I2C pull-up" }
  ],

  "warnings": [
    { "level": "warn", "code": "current_budget",
      "text": "Estimated 320mA peak vs 500mA budget — OK." }
  ],

  "esphome_extras": {
    "captive_portal": {},
    "logger": { "level": "INFO" }
  },

  "fleet": {
    "device_name": "garage-motion",
    "tags": ["outdoor", "porch"],
    "secrets_ref": { "wifi_ssid": "!secret wifi_ssid", "api_key": "!secret api_key" }
  },

  "agent": {
    "session_id": "01J...",
    "history_ref": "sessions/01J....jsonl"
  }
}
​```

## Component library file — `library/components/<id>.yaml`

​```yaml
id: bme280
name: Bosch BME280 (T/H/P)
category: sensor
use_cases: [temperature, humidity, pressure, weather]
aliases: [bmp280, bme680]

electrical:
  vcc_min: 1.8
  vcc_max: 3.6                 # NOT 5V tolerant
  current_ma_typical: 0.6
  current_ma_peak: 4
  pins:
    - role: VCC
      kind: power
    - role: GND
      kind: ground
    - role: SDA
      kind: i2c_sda
      pull_up: { required: true, value: "4.7k", to: VCC }
    - role: SCL
      kind: i2c_scl
      pull_up: { required: true, value: "4.7k", to: VCC }
  passives:
    - kind: capacitor
      value: "100nF"
      between: [VCC, GND]
      purpose: decoupling

esphome:
  required_components: [i2c]
  yaml_template: |
    i2c:
      - id: {{ bus.id }}
        sda: {{ bus.sda }}
        scl: {{ bus.scl }}
    sensor:
      - platform: bme280_i2c
        address: {{ params.address | default("0x76") }}
        i2c_id: {{ bus.id }}
        temperature: { name: "{{ label }} Temperature" }
        humidity:    { name: "{{ label }} Humidity" }
        pressure:    { name: "{{ label }} Pressure" }

params_schema:
  address: { type: string, enum: ["0x76", "0x77"], default: "0x76" }

notes: "3V3 only. On 5V boards, place behind level shifter or use 3V3 rail."
​```

## ASCII diagram format

Pinout block + connection table + passives note. Diff-friendly, README-pasteable.

​```
ESP32-DevKitC-V4 --- garage-motion-v1
+------------------------------------------------------+
|  Rails:  5V (USB), 3V3 (onboard reg), GND            |
|                                                      |
|  GPIO13 ------------------ PIR.OUT     (HC-SR501)    |
|  GPIO21 (SDA) --+--------- BME280.SDA                |
|                 +-[4.7kohm]- 3V3                     |
|  GPIO22 (SCL) --+--------- BME280.SCL                |
|                 +-[4.7kohm]- 3V3                     |
|  3V3   ----------------- BME280.VCC --||-- GND (100nF)|
|  5V    ----------------- PIR.VCC                     |
|  GND   ----------------- BME280.GND, PIR.GND         |
+------------------------------------------------------+

BOM: ESP32-DevKitC-V4, HC-SR501, BME280 breakout, 2x 4.7kohm, 1x 100nF
Power budget: ~12mA idle, ~320mA peak (limit 500mA)  OK
Warnings: none
​```

(Use box-drawing chars in the real renderer; ASCII fallback shown above for portability.)

## First PR scaffolding (proposed)

​```
esphome-studio/
├── README.md
├── LICENSE                    # MIT (matches ESPHome python frontend)
├── pyproject.toml
├── schema/
│   └── design.schema.json     # JSON Schema for design.json (0.1)
├── library/
│   ├── boards/
│   │   └── esp32-devkitc-v4.yaml
│   └── components/
│       ├── bme280.yaml
│       ├── hc-sr501.yaml
│       └── ssd1306.yaml
├── studio/
│   ├── __init__.py
│   ├── model.py               # pydantic models mirroring design.schema.json
│   ├── library.py             # load+validate library files
│   ├── generate/
│   │   ├── yaml_gen.py        # design.json -> ESPHome YAML
│   │   └── ascii_gen.py       # design.json -> ASCII diagram
│   └── validate.py            # esphome config dry-run wrapper
├── examples/
│   └── garage-motion.json
└── tests/
    ├── test_yaml_gen.py
    ├── test_ascii_gen.py
    └── golden/                # YAML + ASCII goldens per example
​```

No agent, no CSP, no API server in PR #1. Goal: `python -m studio.generate
examples/garage-motion.json` produces YAML + ASCII; tests pin them to goldens.

## Agent tool surface (for 0.2)

Discrete operations the LLM is allowed to call:
- `search_components(query)` — fuzzy search KB by name/use_case/alias
- `add_component(library_id, label, params?)` → component_id
- `remove_component(component_id)`
- `set_param(component_id, key, value)`
- `lock_pin(component_id, pin_role, gpio)`
- `set_board(library_id)`
- `solve_pins()` — invokes CSP, returns assignments + warnings
- `generate_yaml()` / `render_ascii()` / `bom()`
- `validate()` — `esphome config` dry-run

Constrained surface = predictable agent.

## Library sourcing strategy

Hybrid. Different parts of the library map to different sources; some are
mineable, some have to be hand-curated.

| Studio field | Best source | Mineable |
|---|---|---|
| Board: `mcu`, `chip_variant`, `platformio_board`, `flash_size_mb` | PlatformIO board JSON ([`platform-espressif32/boards/*.json`](https://github.com/platformio/platform-espressif32/tree/develop/boards), `platform-espressif8266/boards/*.json`) | yes — clean JSON |
| Board: GPIO list + per-pin capabilities (PWM, ADC, strap, I2C, SPI, input-only) | espressif/esp-idf hw-reference + per-module datasheets ([`docs.espressif.com/.../hw-reference/`](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/hw-reference/)) | partial — RST tables, needs scraping |
| Board: rails (5V/3V3/GND, regulator), USB chip | datasheet / dev-board schematic | no — hand-curate one entry per *module class*, not per board |
| Component: ESPHome YAML template + config schema | [esphome/esphome `components/<name>/`](https://github.com/esphome/esphome/tree/dev/esphome/components) — START already plans `schema_gen.py` | yes — ESPHome's own `CONFIG_SCHEMA` (voluptuous) |
| Component: pin role names, required buses, framework constraints | also from the integration code (`PROTOCOL_HOOKS` for I2C/SPI; `cv.GPIOSensor`) | partial |
| Component: voltage range, current draw, pull-up requirements, decoupling caps | datasheet | no — hand-curated, but the agent (0.5) is the natural extractor |

Plan:

- **Don't aim for exhaustive.** Cover the ~30 most common components seen
  across `moellere/esphome` (the survey already enumerated them) and the
  boards actually in use. That's >90% real-world fit.
- **Module classes, not boards.** Curate ESP32-WROOM-32, ESP32-S3-WROOM-1,
  ESP-12F (esp8266), etc. Specific boards (DevKitC-V4, NodeMCU-32S,
  WeMos D1 Mini) inherit pin capabilities from their module and only
  override what they expose differently.
- **Datasheet → component pipeline.** When the agent (0.5) lands, build a
  one-shot tool: feed it a datasheet PDF/URL + an ESPHome integration
  name; it emits a candidate `library/components/<id>.yaml` for human
  review. Same prompt-cached component KB the agent uses for design
  conversations.
- **License hygiene.** Schema-derived data from ESPHome (GPLv3 runtime,
  MIT python frontend) is fine; vendoring source is not. See *License
  hygiene* under Open considerations.

## Open considerations / revisit later

- **Strict-mode toggle.** Per-design opt-in for blocking on electrical violations.
- **Reverse import.** Existing ESPHome YAML → `design.json`. Defer past 0.1
  but keep `connections[]` expressible from a parsed YAML.
- **Multi-device projects.** 0.1 is single-device. Multi-device (e.g. a
  mesh of related sensors sharing secrets/tags) is future scope.
- **Component variants.** BME280 vs BME680 vs BMP280 — `aliases` field is a
  start; full variant inheritance (`extends:`) is later.
- **License hygiene.** ESPHome runtime is GPLv3; python frontend is MIT.
  Schema-derived data is fine; vendoring source needs review. `LICENSES.md`
  from day one.
- **Smoke-test corpus.** Canonical designs (motion, T/H, relay+button, OLED
  clock) with golden YAML+ASCII. Add new one every time the agent guesses wrong.
- **Prompt caching.** Component library easily exceeds 30k tokens — inject
  as single cached block on every Claude API call (use the `claude-api` skill).
- **Validation pass.** Run `esphome config` in a sandbox before declaring
  any design "done" — catches schema drift between our library and ESPHome.

## Pending logistics

- **Branching strategy.** Currently committing direct-to-main with linear
  history. When 0.2 work spans multiple PRs we'll switch to feature
  branches; for now the constraint is that this repo has no other humans
  pushing.
- **Issue tracking.** Once 0.2 (HTTP API) starts, spin off a milestone with
  one issue per endpoint + one for the OpenAPI spec. Same pattern for 0.3
  (one issue per UI panel).
- **License hygiene.** ESPHome runtime is GPLv3; python frontend is MIT.
  Studio is MIT (matches ESPHome python frontend). Schema-derived data is
  fine; vendoring source needs review. Land a `LICENSES.md` when a third
  source enters the tree.

## Reference

- distributed-esphome (sister project): https://github.com/weirded/distributed-esphome
- moellere/esphome (curated device fleet, agent reference corpus): https://github.com/moellere/esphome
- ESPHome upstream: https://github.com/esphome/esphome
- ESPHome schema source: `esphome/schema_gen.py` in upstream
- PlatformIO ESP32 board JSON: https://github.com/platformio/platform-espressif32/tree/develop/boards
- esptool-js (browser USB detect): https://github.com/espressif/esptool-js
- Espressif HW reference: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/hw-reference/