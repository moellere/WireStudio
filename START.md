# esphome-studio — Kickoff State

Handoff doc for starting a fresh session in `moellere/esphome-studio`. Captures
vision, decisions, schemas, and the first-PR plan from the kickoff conversation.

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
- **Knowledge base sources:**
  - ESPHome `schema.json` (from `esphome/schema_gen.py`) for component config keys.
  - PlatformIO board manifests for board catalog.
  - Hand-curated `library/components/<id>.yaml` for electrical metadata
    (pins, passives, power, pull-ups) — ESPHome doesn't carry this.

## Phasing

- **0.1 — MVP, no agent.** Document → artifacts pipeline. 3 boards, ~10
  components. ASCII diagrams. `python -m studio.generate examples/...json`
  produces YAML + ASCII. Goldens pinned in tests.
- **0.2 — Agent layer.** Claude tool-using agent with constrained tool surface
  (see below). Component search, add/remove, param edit, validate.
- **0.3 — CSP solver.** Pin assignment, bus allocation, current budget.
  Recommendation mode ("I want motion detection" → ranked options).
- **0.4 — distributed-esphome handoff.** POST device + YAML, trigger precompile.
- **0.5 — Enclosure suggestions.** Thingiverse/Printables lookup; parametric
  OpenSCAD stretch.
- **Future spec — KiCad schematic + PCB layout.** Reuse the netlist;
  Freerouting for autorouting; Gerber + JLCPCB CPL/BOM export.

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

- **MCP scope.** Claude's GitHub tools were locked to
  `moellere/distributed-esphome` in the kickoff session. New session in
  `moellere/esphome-studio` will need that repo added to the MCP allow-list.
- **Local checkout.** New session should `git clone
  git@github.com:moellere/esphome-studio.git` into the working directory
  before starting.
- **Branching strategy.** TBD. Suggest mirroring distributed-esphome:
  `develop` (integration) + `main` (releases via PR). Confirm at kickoff.
- **CLAUDE.md.** Worth porting the relevant slices of distributed-esphome's
  CLAUDE.md (concision, no-emoji, design-judgment rules, TODO format,
  documentation hygiene). Skip the deployment/test-matrix/HA-specific bits.

## Reference

- distributed-esphome (sister project): https://github.com/weirded/distributed-esphome
- ESPHome upstream: https://github.com/esphome/esphome
- Schema source: `esphome/schema_gen.py` in upstream.