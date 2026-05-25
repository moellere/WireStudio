# Changelog

All notable changes to wirestudio.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Local component inventory.** Track parts on hand in a single
  `inventory.json` (`GET`/`PUT`/`DELETE /inventory`), cross-check a design's
  BOM against it (`POST /design/inventory/check` → have / partial / need),
  and let the recommender prefer parts already in the drawer (`use_inventory`,
  a flat +5 boost). `INVENTORY_PATH` env override for the Docker `/data` volume.
- **ULN2003 stepper driver** library component (28BYJ-48): ESPHome `stepper`
  platform on four control pins, with a KiCad footprint. Baselined for the
  example-coverage gate pending a bundled stepper example.

## [0.13.0] — 2026-05-25

### Added

- **LoRaWAN device target.** A new `lorawan` generation target builds
  RadioLib + LoRaWAN_ESP32 firmware for US915 radio boards, flashes it over
  WebSerial, and provisions devices against ChirpStack — the uplink payload
  and the ChirpStack `decodeUplink` codec come from one field spec, so they
  stay in lockstep. Adds a `wirestudio/targets/` plugin seam (`esphome` wraps
  the existing generators in place), `Design.target` + a `LoRaWAN` config
  block (GPS / DHT22 / OLED), Heltec WiFi LoRa 32 V2 (SX1276) and V3 (SX1262)
  boards, a `/lorawan/*` API, and a web flash dialog. Behind a `[lorawan]`
  extra. Validated end-to-end on a TTGO T-Beam against live ChirpStack 4.17.
- **`make check`** — one local command that runs the same fast gates CI
  runs (ruff, pytest, a clean web build, vitest). Heavy external-CLI
  gates live under `make gates`.
- **Pre-push clean web build.** The pre-push hook now wipes the `tsc -b`
  cache and rebuilds the SPA, so a stale local cache can't pass while a
  fresh-container CI build fails on a real type error.
- **CHANGELOG nudge.** A `changelog` workflow fails a PR that changes
  `wirestudio/` code without touching `CHANGELOG.md`; escape with
  `[skip changelog]` in the PR title or the `skip-changelog` label.
- **`dev` integration branch.** The PR gates and image build now run on
  `dev` as well as `main`; `dev` merges publish a rolling `:dev` image.
- **Side-by-side ArgoCD deploys.** `deploy/overlays/{prod,dev}` +
  `deploy/argocd/` run a pinned-release prod app and a rolling dev app
  from one tree; CI commits the new image sha to the dev overlay on each
  `dev` merge. See `docs/deployment.md`.
- **Footprint coverage + gate (PCB layout, step 1).** Every library
  component (59) and board (23) now declares a real KiCad `footprint`.
  A new `kicad-footprint` workflow clones `kicad-footprints@8.0.0` and
  fails the PR if any referenced footprint doesn't resolve — the
  footprint counterpart to the symbol gate, and the foundation the
  upcoming `.kicad_pcb` emit builds on.

### Changed

- **Version is single-sourced** from `wirestudio/__init__.py`;
  `pyproject.toml` reads it dynamically. Bump it in one place.

## [0.12.0] — 2026-05-23

Headline: three of the four priority tiers (YAML, wiring schema,
enclosure) are now gated in CI; onboard peripherals auto-populate when
you adopt a board; and every library component and board is exercised
by a bundled example (100% coverage, enforced).

### Added

- **Onboard-peripheral auto-populate.** Adopting a dev board — via USB
  detection or **New design** — now seeds its built-in parts (LCD,
  buttons, IMU, RGB/IR, LoRa, GPS, ...) already wired. Covers all 13
  boards that carry `onboard_peripherals` metadata; peripherals with no
  library component (e.g. the AXP192 PMIC) are skipped with a warning.
  New `POST /design/seed_onboard` endpoint.
- **New library components:** `mpu6886` (Atom-family IMU),
  `remote_transmitter` (IR blaster), `i2s_microphone` (I2S/PDM mic).
- **Schematic gate (KiCad) — Verified.** `kicad-schematic` workflow
  runs every example's SKiDL script against the pinned upstream KiCad
  symbol libraries and fails on any unresolved symbol or pin.
- **Enclosure gate (OpenSCAD) — Verified.** `enclosure-render` workflow
  renders every enclosure-capable board's `.scad` and asserts a
  non-empty manifold solid.
- **Coverage `--strict` gate** wired into CI, plus an **`esphome-matrix`**
  workflow that runs the example gate across the pin + latest stables so
  pin bumps are evidence-driven.
- **100% library coverage:** every component (59) and board (21) is now
  exercised by a bundled example that passes both the ESPHome-config and
  KiCad-netlist gates; the `--strict` baseline is empty.
- Agent streaming failure-mode tests; API schema field descriptions.

### Fixed

- USB-connect board detection now matches esptool's detailed chip names
  (e.g. `ESP32-PICO-D4`) to the right board family; the board-picker
  modal scrolls and the confirm button stays reachable.
- ~16 library `kicad:` blocks corrected to real upstream symbols (the
  schematic gate surfaced hallucinated/wrong references).
- `BusList` web build break (missing `useEffect` import).

## [0.11.0] — 2026-05-17

Headline: composite modules, a KiCad schematic renderer, a JLCPCB
feasibility check, a redesigned web UI, and a much wider board library.

### Added

- **Composite modules.** A `library/modules/<id>.yaml` bundles several
  components under one part. Selecting it inserts every component at
  once, each stamped with module provenance, and the BOM collapses the
  bundle to a single line. The web picker gains a "Modules" tab; new
  endpoints `GET /library/modules{,/id}` and `POST /design/insert_module`.
  First module: the 1.3" OLED + EC11 encoder combo.
- **KiCad schematic render.** `POST /design/kicad/schematic` and an
  inline web preview render a design to a KiCad sheet via `kicad-cli`.
  (Phase 2.)
- **JLCPCB feasibility check.** `wirestudio.jlcpcb` cross-checks the BOM
  against JLCPCB part stock and price. (Phase 2.)
- **Compile-status feedback.** Push-to-fleet runs report a compile
  verdict (running / passed / failed) polled from fleet-for-esphome.
- **Board library expansion.** M5Stack Atom-family boards (Atom, Atom
  Matrix, Atom Echo, AtomU, AtomS3, AtomS3 Lite) with bundled examples,
  and the ESP32 C3 / S3 / C6 SuperMini boards. Boards now carry an
  optional product image, surfaced in the board picker.
- **OLED + encoder library.** SH1106 support via a `model` param on the
  ssd1306 component, plus an OLED-knob example.

### Changed

- **Web UI redesign.** Reworked header, left sidebar, and inspector,
  followed by a polish pass on error states, loading/empty
  placeholders, and copy. The board picker is grouped by chip family.
- **Performance.** Library summaries are pre-computed at load; the
  PinoutView memoizes its derived state to cut re-renders.
- **Docs.** Project documentation moved into `docs/`.

### Security

- Fixed a path-traversal vulnerability in the `/examples` endpoint.
- Restricted the previously over-permissive CORS policy to known
  origins.

### Fixed

- The Library Component inspector read the wrong field for notes.

## [0.10.0] — 2026-05-16

Headline: an MCP server that lets a host LLM client drive the studio,
plus a wide cluster of library, agent, and API work.

### Added

- **MCP server.** The design-editing tool surface is exposed over the
  Model Context Protocol at `/mcp` — Streamable HTTP transport mounted
  into the FastAPI app, bearer-token auth (`WIRESTUDIO_MCP_TOKEN` or an
  auto-generated file token). Drive the studio from Claude Code or
  Claude Desktop on a Claude subscription instead of an Anthropic key.
  Phase 1.1 through 1.5:
  - `design-changed` SSE channel (`GET /designs/{id}/events`) so
    browser tabs re-fetch after an MCP write.
  - Seven read-only resources — `library://components{,/id}`,
    `library://boards{,/id}`, `design://{id}/{json,yaml,ascii}`.
  - `set_active_design` pointer so design-bound tools resolve a
    default `design_id` from the browser selection or chat.
  - End-to-end setup walkthrough in `docs/mcp.md` — start the
    daemon, wire up Claude Code / Desktop, chat.
- **KiCad symbol importer.** `python -m wirestudio.kicad.import
  --symbol Lib:Symbol` reads a `.kicad_sym` library and drafts a
  `kicad:` block — or, with `--into <id>`, splices it into an existing
  component with an auto-derived `pin_map`. First of the Phase 2
  knowledge importers.
- **Library batches 2 & 3.** cse7766 + hlw8012 power meters,
  `esp32_rmt_led_strip`, the esp8285-1m board; modbus_controller +
  sdm_meter, bl0906, nextion HMI, and the tuya MCU bridge.
- **Component coverage matrix** (`docs/library-coverage.md`) — which
  library entries have a passing bundled example.
- KiCad `kicad:` symbol mapping completed across the whole library so
  every component and board exports to the SKiDL schematic generator.
- Two environmental-sensor examples (attic-logger, weather-station);
  `Field(description=...)` across the API schemas so `/docs` is
  self-documenting.

### Changed

- **Async API.** `wirestudio/api` endpoints migrated to `async def`;
  the fleet client rewritten on `httpx.AsyncClient`. `slowapi` rate
  limiting on the agent endpoints; CORS origins read from
  `WIRESTUDIO_ALLOWED_ORIGINS`. `DesignStore` and `SessionStore`
  extracted as `typing.Protocol` interfaces.
- **Agent cost tuning.** Configurable model tier via
  `WIRESTUDIO_AGENT_MODEL`, prompt-cache breakpoints, and a slimmer
  system payload — markedly cheaper per turn.
- Web UI gains a basic / advanced mode toggle that hides the
  lighter-checked surfaces by default.
- References to the OTA-deploy companion project updated
  `distributed-esphome` → `fleet-for-esphome` (upstream rename).

### Fixed

- Multi-turn agent regression — assistant blocks are stripped of SDK
  parser metadata before they are appended to history.
- `add_bus` fills missing pin fields from `board.default_buses`; the
  YAML renderer is guarded against `StrictUndefined`.
- `esp32:` chip-block emission corrected for every ESP32-family
  variant.

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
  fleet-for-esphome ha-addon (`FLEET_URL` + `FLEET_TOKEN`). Optional
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

[Unreleased]: https://github.com/moellere/wirestudio/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/moellere/wirestudio/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/moellere/wirestudio/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/moellere/wirestudio/releases/tag/v0.9.0
