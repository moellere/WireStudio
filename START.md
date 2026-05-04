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
- Bus editor in the UI
- Strict-mode pin locks (`locked_pins` already in schema)
- Frontend RTL/jsdom component tests
- Full SSE/WS log relay (current 0.7+ uses HTTP polling at 1.5s intervals)
- Capability picker: bus-aware constraint pre-fill (auto-set required_bus
  from the design's existing buses so I2C designs don't surface SPI parts)
- Capability picker: per-result "alternatives" tooltip surfacing the
  recommender's full ranking when the user wants to compare

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
- **0.8 — Enclosure suggestions.** Thingiverse/Printables lookup against
  the chosen board + components; parametric OpenSCAD stretch.
- **Future — KiCad schematic + PCB layout.** Reuse the netlist; Freerouting
  for autorouting; Gerber + JLCPCB CPL/BOM export.

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