# Changelog

All notable changes to wirestudio.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

(no changes since v0.9.0)

## [0.9.0] — 2026-05-05

First tagged release. Covers the full arc from the initial generator
pipeline (0.1) through the KiCad schematic exporter (0.9). Future
entries record only what changed since the prior tag.

### Pipeline (0.1 → 0.6)

- **0.1 — Generator pipeline.** `design.json` (JSON-Schema-validated)
  → ESPHome YAML + ASCII wiring diagram + BOM via pure functions over
  the static library. CLI: `python -m wirestudio.generate <design.json>`.
- **0.2 — HTTP API.** FastAPI server at `python -m wirestudio.api` exposing
  the same generators over `/library/*`, `/design/*`, `/examples/*`.
  Auto-generated OpenAPI docs at `/docs`.
- **0.3 — Web UI v1.** React 19 + Vite + Tailwind v4 three-pane shell.
  Editable: board picker, fleet metadata, requirements, warnings,
  per-component params, per-connection targets. Add/remove component
  instances with auto-wiring (rails by voltage match, bus pins to a
  matching bus, missing buses auto-prepended from `default_buses`).
  Debounced render (250 ms) into local state. Reset / Download JSON
  buttons.
- **0.4 — USB device bootstrap.** "Connect device" header button runs
  `esptool-js` over WebSerial. Reads chip family + MAC, normalises
  the chip name, filters board library to candidates with the matching
  `chip_variant`, seeds a fresh `design.json` on adopt.
- **0.5 — Agent layer.** Claude tool-using agent (`wirestudio/agent/`)
  with a constrained tool surface: `search_components`, `add_component`,
  `set_param`, `set_connection`, `solve_pins`, `recommend`, etc. Session
  history at `sessions/<id>.jsonl`. SSE streaming variant via
  `client.messages.stream()`. Recommendation mode.
- **0.6 — CSP pin solver.** Auto-assigns every unbound connection.
  GPIO with empty pin → board GPIO matching the library role; bus
  pins → matching design bus; expander pins → next free slot on the
  first `io_expander`. Conflicts + current-budget overruns surface as
  warnings. Boot-strap-aware preference (avoids `boot_high`/`boot_low`
  pins for outputs unless forced).
- **Compat checker.** `wirestudio/csp/compatibility.py` validates pin
  capabilities across the design: input-only-as-output, boot-strap
  conflicts, serial-console reuse, voltage limits, ADC2/WiFi conflict
  on classic ESP32, locked-pin-vs-bound divergence, locked-pin-cap
  mismatch.

### Fleet handoff (0.7)

- **`POST /fleet/push`** ships the rendered YAML to a configured
  distributed-esphome ha-addon (`FLEET_URL` + `FLEET_TOKEN`). Optional
  `compile: true` enqueues an OTA build. Header **Push to fleet**
  modal with status banner, device-name input, compile checkbox.
- **Build-log polling** at `GET /fleet/jobs/{run_id}/log?offset=N`;
  the dialog tails it at 1.5 s into a scrolling viewer once a compile
  is enqueued.
- **SSE log relay** at `GET /fleet/jobs/{run_id}/log/stream` —
  server-side polls the addon at ~300 ms and streams Server-Sent
  Events. Client uses `EventSource` first, falls back to polling at
  the last accepted offset on transport error.
- **Strict-only push** — `strict: true` on `POST /fleet/push` refuses
  the upload when warn/error compatibility entries remain, mirroring
  the `POST /design/render?strict=true` envelope. Header gains a
  global **strict** toggle (amber when on); the dialog renders a
  matching notice.

### UX accumulated through 0.7+

- **Capability-driven "Add by function" picker.** New `GET
  /library/use_cases` aggregates the canonical capability vocabulary;
  two-pane dialog ranks library components for the picked use case
  (or free text), with an alternatives disclosure showing score deltas
  and a one-click add per result.
- **Pin locks.** `locked_pins[role] -> pin` per component. Solver
  applies locks (force-fills empty bindings, flags mismatches).
  Inspector gains a 🔓/🔒 toggle next to each gpio pin selector.
- **Bus editor.** Inspector design view gains a Buses section. Rename
  bus id (atomic — rewrites every `connection.target.bus_id`),
  edit per-type pin slots, add / remove buses, inline compatibility
  warnings filtered to each bus card.
- **Drag-and-drop pinout.** Per-instance Pinout view with two-column
  layout: board GPIOs (with capability badges) on the left,
  draggable connection chips on the right. Drop fires a connection
  rewrite. Conflict detection paints rose; current binding glows
  emerald.
- **Server-side design persistence.** `designs/<id>.json` store
  with `GET / POST / DELETE /designs[/<id>]`. UI gains a **Saved**
  tab and a **New design** dialog seeded from a board pick.

### Library expansion

41 components, 13 boards. Every entry carries a `kicad:` mapping
(see "KiCad schematic export" below) and most carry `enclosure:`
metadata for the OpenSCAD generator.

- **Sensors:** BME280, BMP180, BMP280, HTU21D, DS18B20, MPU6050,
  HC-SR501 (PIR), HC-SR04 (ultrasonic), RCWL-0516 (microwave radar),
  TSL2561 (lux), MAX31855 (K-type thermocouple, SPI), HX711 (24-bit
  load-cell ADC), DHT11/22, LD2420 (mmWave radar), CC1101 (sub-GHz
  radio), pulse_counter, rotary_encoder.
- **ADCs / IO:** ADS1115 hub + per-channel components, MCP23008,
  MCP23017, gpio_input / gpio_output, adc.
- **Displays:** SSD1306 (I2C OLED), ST7789 (SPI TFT), ILI9xxx (SPI),
  LCD-PCF8574 (I2C character LCD), MAX7219 (LED matrix), TM1638,
  XPT2046 (touch).
- **RF / RFID:** RC522, RDM6300, SX127x (LoRa), uart_gps,
  rf_bridge.
- **Audio:** MAX98357A (I2S DAC + amp), RTTTL piezo.
- **Light:** WS2812B, APA102.
- **Hub / camera:** esp32_camera, ads1115_channel.
- **Boards:** wemos-d1-mini, esp32-devkitc-v4, nodemcu-32s,
  nodemcu-v2, ttgo-lora32-v1, esp01_1m, esp32-c3-devkitm-1,
  esp32-s3-devkitc-1, esp32-wrover-cam, esp32cam-ai-thinker,
  m5stack-atom, m5stack-atoms3, ttgo-t-beam.

### 1-wire bus type (0.7+)

`Bus.pin` field added; `1wire` rendered as a top-level `one_wire:`
block. Multiple DS18B20s on the same physical wire share a single
bus block plus N `dallas_temp` sensors. New `examples/multi-temp.json`
+ golden artefacts.

### Schema extension: `kind: "component"` connection target (0.9)

Lets one component instance reference another by id (`ads1115_channel`
→ `ads1115` hub). `parent_library_id` on the library `Pin` constrains
the reference; the solver auto-binds. Channels become first-class
inspector citizens with their own params row instead of being buried
inside an `array` param. ConnectionForm gains a `component` kind in
the dropdown with a sibling-instance picker.

### 0.8 — Enclosure suggestions

- **v1 — Parametric OpenSCAD generator.** Each dev-board YAML carries
  an `enclosure:` block (PCB outline, mount holes, port cutouts).
  `wirestudio/enclosure/openscad.py` emits a self-contained `.scad` shell
  with tunables (wall, floor, clearance, standoff geometry) at the
  top so the user dials in fit without re-rendering.
- **v2 — Thingiverse search relay.** Pluggable per-source search at
  `wirestudio/enclosure/search.py`. Thingiverse implementation gated on
  `THINGIVERSE_API_KEY`. Printables deferred (no public API yet);
  source stays in the catalogue with `available: false, reason:
  "Printables search deferred -- no public API yet"`. `GET /enclosure/
  search` + `GET /enclosure/search/status`.
- Header **Enclosure** button opens a tabbed dialog (Generate /
  Search community models).

### 0.9 — KiCad schematic export

- **`KicadSymbolRef`** on `LibraryComponent` + `LibraryBoard`:
  `symbol_lib`, `symbol`, `footprint`, `pin_map` (role → KiCad pin
  name), optional `value` override. 100 % library coverage (41
  components + 13 boards).
- **`wirestudio/kicad/generator.py`** walks `design.json` and emits a
  SKiDL Python script. The studio doesn't import or run SKiDL itself
  — this keeps the artefact transparent (the user can `cat`/edit it)
  and avoids adding numpy + EDA-toolchain weight to the server.
- **`POST /design/kicad/schematic`** returns the script with
  `Content-Disposition: attachment`. Header **Schematic** button
  opens a download dialog with usage instructions and a SKiDL doc
  link. PCB layout deferred to 1.0+.

### Deployment (Docker + GHCR)

- **Multi-stage `Dockerfile`** — `node:20-alpine` builds the SPA,
  `python:3.11-slim` ships the bundle. tini for signal handling.
  ~180 MB; `linux/amd64` + `linux/arm64`. `EXPOSE 8765`,
  `VOLUME /data`.
- **`wirestudio/api/serve.py`** mounts the studio app at `/api` and the
  built bundle at `/`. Bare-API mode preserved (Vite dev keeps
  working).
- **`SESSIONS_DIR` + `DESIGNS_DIR`** env vars route the stores at
  `/data/sessions` + `/data/designs`.
- **GitHub Actions** (`.github/workflows/docker.yml`) publishes to
  `ghcr.io/moellere/wirestudio` on push-to-main and `v*` tag
  push. Multi-arch via `docker/build-push-action` + GHA cache.
- **Two-service compose recipe** in `deploy/` for users who want
  nginx in front (HTTP/2, brotli, scaling api workers
  independently). Documented as opt-in, not the default.

### Test surface

297 pytest, 125 vitest. Goldens for every bundled example pin both
YAML + ASCII output. RTL/jsdom component tests cover BusList,
ConnectionForm, EnclosureDialog, Inspector, CapabilityPickerDialog,
PinoutView, PushToFleetDialog, SchematicDialog. ruff + tsc + vite
build clean across the whole arc.

[Unreleased]: https://github.com/moellere/wirestudio/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/moellere/wirestudio/releases/tag/v0.9.0
