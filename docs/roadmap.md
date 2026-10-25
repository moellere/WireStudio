# Roadmap to 1.0

Written against 0.39.0 (2026-10-18). Per-release deltas stay in
[`CHANGELOG.md`](../CHANGELOG.md); the status table in the
[README](../README.md#status) is the live record of what is verified.
This page says what 1.0 means, what has to land to get there, and what
is deliberately left out.

## What 1.0 means

The studio already has the surface area of a 1.0. What it does not yet
have is the set of promises a 1.0 makes. Four of them:

1. **`design.json` is stable.** `schema_version` moves from `0.1` to
   `1.0` once, with a migrator, and after that no breaking change ships
   without one. A design saved under 1.0 loads under every later 1.x.
2. **Nothing is advertised without a gate.** Every row in the README
   status table is either *Verified* (a CI or nightly gate fails the PR
   or the night) or *Experimental* (hidden behind the advanced toggle,
   with the caveat on the row). The middle tier, *Works (lighter
   checks)*, is gone: each entry is promoted or demoted.
3. **Install and upgrade are boring.** `pip install wirestudio` and the
   image upgrade in place: stores migrate, the user library survives,
   the pinned ESPHome has a published support table, and third-party
   data in the tree has its licence recorded.
4. **The agent and MCP surfaces are measured, not just present.** A
   fixed task list scores the agent; an MCP client exercises the server
   in CI.

Everything below is ordered by which promise it serves. Version numbers
are nominal: one theme can span two minors, two themes can share one.

## 1. Model completion and schema freeze

The last planned changes to the document shape, then the freeze.

- **0.40 — Connectors** ([#300](https://github.com/moellere/WireStudio/issues/300)).
  Pin kind `passthrough` and connection target `net`, so a harness
  connector can put pads on a subcircuit's internal nets and on lines
  another component already owns. Connector family `connector_1x02` …
  `connector_1x08` plus a 2x05 IDC, footprint from a `family` param.
  A desk-bike-shaped example pins the netlist. Closes the last "finish
  it by hand in KiCad" gap on the schematic.
- **0.41 — Retire the standalone LoRaWAN sugar.** `design.lorawan.gps`
  / `dht22` / `oled` lower to library components internally, so the Arduino path reads the same
  `components` / `buses` / `connections` the ESPHome generator does.
  The 1.0 schema drops them; the migrator rewrites any still in a document.
- **0.42 — Migration mechanism.** `wirestudio.migrate`: a chain of
  per-version functions over the raw document, run on load by the
  design stores, the CLI (`wirestudio migrate design.json`), the REST
  `POST /designs` path and `create_design` on MCP. A test loads every
  bundled example and every golden through it. The first real step is
  the sugar rewrite above; `0.1 → 1.0` is the second, cut at release.
- **Schema audit before the freeze.** One pass over
  `design.schema.json` for fields that exist for one example, names
  that differ between the schema and the API, and anything the
  generators ignore. Each is removed, renamed, or documented as
  deliberate. This is the only window to do it without a migrator step.

## 2. Promote or demote every "Works" row

The middle tier today, and what moves each row.

| Row | What promotes it | If that cannot happen |
|---|---|---|
| LoRaWAN standalone and external-component paths | **promoted.** The firmware builds and `esphome config` gate the code every PR; the nightly hardware gate asserts the four Wyola boards running the two paths are on the bench, logging and heard by ChirpStack within the hour. Not reflashed nightly (a rejoin and a DevNonce each time) | |
| Remote workbench | same gate, plus the transport tests already there | same |
| Meshtastic flash + config | nightly flash of a radio board, boot verdict by banner once one is established upstream, config read back | demote to *Experimental* |
| CircuitPython flash + code.py | nightly flash, boot verdict by the serial banner, `code.py` runs without a traceback on the serial console | demote |
| MicroPython flash + main.py | nightly flash, REPL banner, `main.py` runs without a traceback | demote |
| Component authoring | **promoted.** A user component goes through `esphome config` in the config gate; `tests/test_component_corpus.py` holds the check gate to a corpus of bad components | |
| ESPHome dashboard compile | **promoted.** The nightly `dashboard` job runs a real ESPHome Device Builder, open and password-protected, and pushes, compiles and fetches through the studio's client with the wire assumptions asserted | |
| MCP server | **promoted.** `tests/test_mcp_client.py` drives the mounted server with the `mcp` package's client, every PR; the suite itself now runs in CI (`tests.yml`), which no row could claim before | |
| Thingiverse relay | nothing; third-party ranking | stays *Experimental* |
| Agent | **promoted.** The eval harness (section 5) scores the reference solutions every PR and Claude Code nightly, held to `gate.claude_code_min_pass` (24 of 28) | |

### The nightly flash stage (workbench phase 3)

The stage is written: a roster entry with `board:` and `flash:` gets
each listed framework written with a full erase and its boot marker
asserted (`docs/workbench.md`, "The gate"). It needs the dedicated
boards on a bench: one plain ESP32-S3 for ESPHome, CircuitPython and
MicroPython, one radio board for Meshtastic. Every board on the
reference bench carries live traffic, so none of them can be the one.

Once it runs, the README rows cite the job, and the promote/demote pass
follows its first green week. CircuitPython's marker is its serial
banner, taken from the first covbench run; Meshtastic's is its
"Booted, wake cause" log line, from the second. The LoRaWAN paths are not among the frameworks the stage
writes, because a nightly reflash of a LoRaWAN device spends a
DevNonce and a join; their rows are *Verified* on the build gates and
the nightly uplink check instead. The CronJob
stays inside the cluster (a public repository cannot run fork PRs
against a bench), so a failed Job is the report, as with the rest of
the gate.

### Functional loop (workbench phase 4)

Not started. For the ESPHome tier it is the difference between "boots"
and "works": provision against the bench's AP, assert the device's
native API answers and the expected entities appear (a sensor reading,
a switch that toggles), assert an MQTT publish for the `base_mqtt`
shape. For radio boards an SDR power-spectrum capture during TX catches
the deaf-radio wiring bug (an undriven FEM pin) that serial cannot.
Phase 4 is a 1.0 stretch goal: it raises the ESPHome tier from
*compiles and boots* to *behaves*, but 1.0 can ship without it if the
flash stage is in.

## 3. Framework parity and library coverage

Components each framework's generator can use today, out of 102
(Tasmota autodetects I2C parts, so they count without a block):

| Framework | Usable |
|---|---|
| esphome | 102 |
| tasmota | 75 |
| circuitpython | 89 |
| micropython | 89 |
| wled | 29 |
| lorawan | 53 |

100% is the wrong bar: a Tuya MCU bridge has no CircuitPython meaning.
The bar is the one `library-coverage.md` already holds ESPHome to:
**zero unexplained gaps.** That gate is in: `scripts/coverage_matrix.py`
carries a column per framework, `scripts/framework_baseline.yaml` holds
one reason per missing block (`no driver upstream`, `no meaning on this
framework`, `deferred: needs X`), and `--strict` fails the PR on a gap
with no entry, a stale entry, or a reason outside those three.
`library-coverage.md` lists every gap under "Framework gaps". What
remains is to work the baselines down:

- **CircuitPython and MicroPython** share the same fragment shape, and
  both now cover every part with a driver: the Adafruit bundle or a core
  module on CircuitPython, a `mip` driver or `machine` on MicroPython
  (motors, steppers, displays, IR, LoRa, ADCs, load cells, PM and GPS
  over UART, counters, plain outputs). Parts with no permissively
  licensed driver are datasheet code, run against a fake bus in
  `tests/test_micropython_registers.py`; `tests/test_python_blocks.py`
  runs every block of both frameworks for a loop pass against stub
  modules. The UART parts with a documented frame (MH-Z19, CSE7766,
  RDM6300, LD2410, LD2420, the RF bridge, Nextion touch events and
  BL0906 register reads) decode it in shared datasheet code on both,
  tested in `tests/test_uart_frames.py`; the register-level BMP180,
  MPU6886 and AXP192 and the HLW8012's pulse rates likewise, tested in
  `tests/test_register_code.py` (the BMP180 against the datasheet's
  worked example), and the XPT2046, the PCF8574 character LCD, the
  MFRC522 (REQA through each cascade level's SELECT, with CRC_A),
  MicroPython's MCP23S17 and MicroPython's PN532 (I2C frames, ACK and
  NACK) likewise; the bit-banged TM1637 and TM1638, the CT clamp's RMS
  and MicroPython's Wiegand reader likewise, tested in
  `tests/test_pin_protocols.py`. Battery sense rides the `adc` part the
  board's divider is seeded as, whose blocks apply its `multiply`
  filters. The I2S parts use each framework's own audio API (PDM input
  on CircuitPython, I2S input on MicroPython, I2S output on both), the
  clocks taken from the design's `i2s` bus; the camera is
  CircuitPython's `espcamera`. Modbus RTU (with the PZEM-004T and SDM
  meters) and the Tuya MCU protocol (with its sensors and switches) are
  protocol code too, tested against a simulated peer in
  `tests/test_uart_frames.py`; a part that hangs off a hub reaches the
  hub's helpers through `parent`, which also gives the ADS1115 and
  MCP3008 channels their own reads. What remains in both baselines is
  reasons rather than work: passive parts, the CC1101, CircuitPython's
  Wiegand (no pin interrupts) and MicroPython's camera (no module in the
  generic image).
- **Tasmota** covers what Tasmota's template format can express: 75
  parts, with the function ids computed per build, since an ESP8266
  build numbers every function after the enum's first `#ifdef ESP32`
  block lower than an ESP32 build does. A part on a hub (a Modbus meter)
  maps through the hub's UART. What the baseline still defers is the
  H-bridge (no function; it needs rules), the Sonoff RF Bridge (a BASE
  module, not a GPIO function), the BL0906 and the Universal Display
  panels (a `display.ini` beside the template); the rest are reasons,
  not work.
- **LoRaWAN** has blocks for the boards' own peripherals and for 48
  parts: the I2C environment, light, distance, current, motion and
  register-level parts, the DS18B20, the ADC parts and hubs, the pin
  parts (counters, encoder, ultrasonic, load cell, CT clamp), the UART
  sensors (MH-Z19, PMSx003, LD2410, LD2420, CSE7766, BL0906), each bus on
  its own hardware UART; the SPI MAX31855 and MCP3008 with its channels,
  on the radio's bus; a Modbus RTU hub with the PZEM-004T and SDM
  meters; and the event parts (PN532, Wiegand, IR receiver), which
  carry the last id seen, a count and its age. Each adds named fields
  to the payload codec, per instance where a part can repeat. The frame decoders are C++ ports of the
  Python blocks', run on the host against the same frames in
  `tests/test_lorawan_fragments.py`, and the `lorawan-firmware` gate
  builds designs that carry every block, so a library or API mismatch
  fails the PR that brings it. What remains in the baseline is
  reasons, not work: actuators, lights, displays and expanders have
  nothing to report, and the radio comes from the board.
- **WLED** has both tiers: the runtime one (LED outputs, buttons, IR,
  relay as `cfg.json`) and the compile-in one (a `usermod` block that
  emits a `platformio_override.ini` environment, built by `wled_build`
  and the `wled-firmware` workflow against v0.15.2). Eighteen parts
  carry usermod blocks (the I2C sensors, the DS18B20 and DHT, the
  Battery reader, the LD2410, the I2S microphone as audioreactive, the
  rotary encoder, the buzzer, and the SSD1306 and ST7789 displays), and
  the analog inputs are WLED's analog button; the workflow builds the
  usermods five to a design on PRs that touch a component file. The
  baseline holds two deferred entries: the PWM fan, whose usermod needs
  a temperature usermod compiled in beside it, and the ADS1115, whose
  usermod's Adafruit BusIO does not find SPI.h in the release's
  environment. When the pin moves to 0.16 the override switches from build
  flags to `custom_usermods`.

Boards: all 26 have an ESPHome example. The enclosure block is on 11.
Section 4 covers the rest.

## 4. Physical outputs

- **PCB.** Routed DRC is in the UI
  ([#344](https://github.com/moellere/WireStudio/issues/344)): a route
  runs KiCad DRC on the result and the Schematic dialog, the
  `/design/kicad/route/{key}/drc` endpoint and `route_pcb` report it,
  with the footprint-inherent types waived in one list
  (`wirestudio.kicad.drc.WAIVED`) the CI gates share. Route parameters
  ([#345](https://github.com/moellere/WireStudio/issues/345)): via cost
  and keepout rectangles from the dialog, the API and `route_pcb`, with
  the `pcb-route` gate checking both take effect. A GND pour on B.Cu
  ([#346](https://github.com/moellere/WireStudio/issues/346)), filled
  after the route so Freerouting treats GND as a plane; the gate checks
  every routed board fills it and that it reaches the Gerbers. A supply
  pour on top is left out: on two layers it would split the signal
  layer. An example ordered from JLCPCB and brought up on the
  bench would be the only test of the fab bundle beyond its structural
  checks; it is not a 1.0 gate.
- **Enclosure.** `enclosure:` metadata for every board whose outline
  is published: eleven have it, the ESP32-C3 and S3 DevKits from
  Espressif's dimension drawings. Of the other fifteen, the six M5Stack
  Atoms ship in their own case, the ESP-01 and ESP8285 are modules for
  a host board, and the two camera boards need a lens window in the lid
  that the generator does not cut. The S3 and C6 SuperMinis, the Heltec
  V2 and V4 and the T-Beam wait on a published drawing. YAPP_Box is
  adopted: the `.scad` endpoint inlines the pinned generator and drives
  it from the `enclosure:` block, base and lid with a ridge and snap
  joins. The fit test runs through print-warden: one enclosure sent with
  `print_enclosure`, printed, fitted to its board and photographed in
  the docs.
- **Schematic.** 0.40 draws the sheet itself (board, peripherals,
  subcircuits as blocks, PWR_FLAGs, no-connects) and
  `scripts/check_sch.py` has kicad-cli read every example's netlist back
  from the geometry. Every subcircuit is drawn from its `schematic:`
  layout, and `check_sch.py` fails a layout that leaves a pin to the
  fallback stub. Boards drawn as generic headers carry a `kicad.pin_map`
  transcribed from the vendor's own header documentation
  ([#312](https://github.com/moellere/WireStudio/issues/312)).
  `global_label_dangling` stays in the ERC baseline only for
  onboard parts on GPIOs no header breaks out. After that the
  baseline holds only what KiCad's pin types cannot express (the
  passive-header `pin_not_driven` cases and SPI's shared MISO). ERC
  checks the sheet inside a project whose `sym-lib-table` names the
  pinned symbol libraries, which retired the library-table warning.

## 5. Agent and MCP

- **Agent eval harness.** In. `wirestudio/agent/eval_tasks.yaml` is
  the fixed task list: twenty-eight natural-language asks across eleven
  bundled examples (add a sensor, move it to a bus, resolve a pin
  conflict, build a driver from blocks, swap the board, answer without
  editing), each with a tool-call budget and a reference solution.
  `python -m wirestudio.agent.eval` scores the design the agent hands
  back on three things: it validates (every pin bound and on the
  board, no pin shared, every bus complete, `esphome config` accepts
  the render), the asked-for change is present, and the turn stayed
  within budget. The `agent-eval` workflow replays the reference
  solutions through the same scorer on every PR that touches the
  agent, and runs the model nightly and on dispatch with the score in
  the job summary; `gate.min_pass` holds the pass count. The README
  row is promoted. The nightly run uses Claude Code over the MCP
  endpoint on the owner's subscription (`CLAUDE_CODE_OAUTH_TOKEN`),
  held to `gate.claude_code_min_pass`; the embedded agent is scored
  too whenever `ANTHROPIC_API_KEY` is set. Both gates are 25 of 28:
  the embedded agent scored 26 twice on one commit (2026-10-24, its
  first scored runs) and Claude Code 27 twice and 26 once the same day.
  A model swap is a dispatched run and a diff of two summaries.
- **MCP conformance in CI.** Done. `tests/test_mcp_client.py` runs
  the `mcp` client library against the mounted server under uvicorn:
  connect with the token, list tools and resource templates,
  `create_design` → `add_component` → `solve_pins` → `validate` →
  `render`, read `design://{id}/yaml` and a library resource, and a
  client without the token is refused. The server emits no change
  notifications, so there is no event to assert.
- **Cost line.** Done. `search_components` returns each match's id,
  name, category and a relevance score, best first, about half the
  bytes of the old cards; `library_detail` carries the rest. The
  embedded agent's `max_iterations` is 8: the largest task budget is
  six tool calls, so a turn within budget needs at most seven model
  calls. The Claude Code eval measures the search change against the
  first nightly baseline.

## 6. Operations and hygiene

- **`LICENSES.md`.** Done. One file naming every third-party source:
  the data derived into the tree (Tasmota function ids, WLED keys and
  usermods, the Meshtastic variant map, CircuitPython and MicroPython
  board ids, KiCad symbol and footprint references, ESPHome's
  configuration shape), the libraries the generated firmware names,
  the packages in the web bundle, what the images fetch at build, and
  what the firmware proxies relay without storing, each with its
  licence.
- **ESPHome support table.** Done. `esphome-matrix` sweeps the pin,
  the stables since and the floor, `check_examples.py --json` records
  each release's verdicts, and `scripts/esphome_support.py` charges
  every failure to the library components ESPHome's error names and
  writes `docs/esphome-support.md`: the supported range in one line,
  a row per release, and a row per failing component. The committed
  table is held to the committed sweep results by a test.
- **Store migrations.** Done. Each SQLite store carries a schema
  version (`PRAGMA user_version`) and a list of steps that
  `wirestudio.sqlite_store` runs on open, one transaction per step,
  under a write lock; a file from before versioning is adopted at
  version 1 with its rows, a file from a newer release is refused. The
  JSON stores need nothing beyond the design migrator. Backup and
  restore for both layouts is in `docs/deployment.md`, with an online
  backup command for the SQLite files.
- **Upgrade test.** Done. The `upgrade` workflow installs the newest
  release from PyPI into its own venv and has it write a data
  directory through its own REST API, in both store layouts: every
  example it bundles saved as a design, a user component and a design
  that uses it, inventory and an agent session. The checkout then
  opens that directory and must load every design at the current
  schema and render it exactly as the original document renders, and
  read back the user component, the inventory, the sessions and the
  SQLite stores at their current versions (`scripts/check_upgrade.py`).
  Run here against 0.40.0, which predates the design migrator: all 75
  designs in both layouts pass.
- **Workflow actions.** Done: every action the workflows use is on its
  current major and the Node 24 runtime, so the Node 20 deprecation
  warning is gone from the job logs.
- **Flash size measurement** ([#219](https://github.com/moellere/WireStudio/issues/219)).
  Code is done; the four named boards need `esptool flash-id` once each
  when they reach the bench. Not a 1.0 blocker.

## 7. Documentation for 1.0

- The README status table becomes the 1.0 contract: two tiers,
  *Verified* and *Experimental*, every row citing its gate.
- `START.md` consolidated. Done: the decisions it held are in
  `docs/architecture.md` (the document rules, the reasoning layers, no
  LLM in a compile path, MCP transport and auth, the framework / build /
  network-server axes, the library split), the schema in
  `docs/design-schema.md` (generated from `design.schema.json` and held
  to it by a test), library sourcing in `docs/library.md`, and the
  LoRaWAN region design in the LoRaWAN plan. `START.md` is the resume
  block and a pointer; the CLAUDE.md TODO convention cites this roadmap.
- `docs/user_guide.md` covers the paths that landed since it was
  written. Done: inventory, component authoring, the six-framework
  flash dialog, the workbench, both ESPHome build paths, the other
  frameworks' outputs and the PCB / fab path, and every bundled
  example in its table.
- Release notes for 1.0 list the migrations and the tier changes, not
  the features. Drafted in [`release-notes-1.0.md`](release-notes-1.0.md);
  the `0.3 → 1.0` step is written, and the rows the flash stage decides
  are filled in at release.

## 8. Community designs and templates

[#357](https://github.com/moellere/WireStudio/issues/357), from
@agripnt. Moved into 1.0: a catalogue people can browse, import from
and submit to is the most direct way to bring users in, and the schema
it depends on is frozen at 1.0.

- **Catalogue (built).** `moellere/wirestudio-designs`. A design is a
  folder: `design.json`, a `meta.yaml` (author, tags, and optional
  `derived_from` and `source`) and an optional `README.md`. The name
  and board come from the design itself. Every design is CC-BY-4.0.
  After each merge, CI publishes `index.json` to the repository's
  `index` branch.
- **Review (built).** Submissions arrive as pull requests, and the
  owner approves every merge. CI checks four things:
  - the design loads in WireStudio after migration;
  - its render passes `esphome config`;
  - it holds no literal credentials;
  - the folder holds nothing but those three files.

  WireStudio and ESPHome are pinned in the catalogue's
  `requirements.txt`.
- **Studio (built).** A "Gallery" sidebar tab reads the index from
  `WIRESTUDIO_DESIGNS_REPO` (default `moellere/wirestudio-designs`; a
  fork works the same way, and empty turns it off).
  - **Import** opens a design like an example. It records `origin`
    (catalogue, slug, author, license) so the credit survives edits.
  - **Share** refuses literal credentials and downloads the folder as
    a zip. Its `meta.yaml` carries `derived_from` when the design came
    from the catalogue. Share then opens the catalogue's upload page;
    the user drags the folder in and opens the pull request, so the
    studio holds no token. A pre-filled new-file URL was ruled out: it
    carries one file, and a design and its meta are two.
- **User components, studio checks, custom code (built).**
  - **User components.** A design ships the components its author
    wrote, under `components/`. CI runs each through the component
    gate. Import installs them, and never over a different one of the
    user's own. Share packs them.
  - **Studio checks.** CI runs the studio's validate checks. An error
    fails the design; a warning goes to the reviewer.
  - **Custom code.** A design with a lambda, `external_components`,
    `includes` or `libraries` is flagged for review and badged in the
    Gallery.
  - **Seeds.** The catalogue launched with 14 of the owner's designs.
- **Photos (built).** Up to four per design. CI checks their shape: a
  still JPEG, PNG or WebP under 1 MB and 2048 px with no EXIF/XMP.
  Share re-encodes attached photos to fit and strips their metadata;
  `scripts/strip_photos.py` does the same for a by-hand submission.
  Content is the owner's review: the studio shows only merged photos,
  and CSAM detection is GitHub's platform-level PhotoDNA scanning. No
  classifier runs in CI -- pull requests from forks get no secrets for a
  cloud moderation API, and nothing CI does can stop an upload, only a
  merge.

## 9. Design system

A design package for the web UI is being written in a separate session
as a Design System artifact (`wirestudio`, synced from `web/src` at
2050b2b): `tokens.json` (both themes), a brand-book README, fonts, and
cards for the seven shared primitives in `ui.tsx`, `Status.tsx` and
`SolveResultBanner.tsx` plus the inline patterns (`PinTag`,
`CompatibilityRow`, `Section`, `KeyValueRow`, `ListRow`, `Chip`,
`Notice`, `WarningList`), with the header toolbar, tabs and banners in
progress. It describes the UI as built, so adopting it is a refactor
with a few deliberate fixes, not a redesign. It lands before the 1.0
release PR and does not touch the green-week clock.

- **Tokens are the source.** The package's `tokens.json` goes in the
  tree at `web/design/tokens.json`; a script writes the `@theme` block
  and the `[data-theme="light"]` overrides in `web/src/index.css` from
  it, and a test fails when the two disagree. The emerald, amber and
  rose dark values the CSS now inherits from Tailwind's defaults are
  stated in the tokens.
- **The inline patterns become components.** Done: `Section`,
  `KeyValueRow`, `ListRow`, `Chip`, `Code`, `Notice`, `PinTag` and
  `CompatibilityRow` are exported from `ui.tsx` and the screens use
  them, so the cards can mount real components instead of static
  renditions. `WarningList` and `RequirementList` stay in
  `Inspector.tsx`: they are forms bound to `design.json` with one use
  each. Per-dialog markup is left alone unless it repeats one of them.
- **The contrast flag is fixed.** `ink-faint` reads 4.0:1 on
  `surface-0` in dark and 4.4:1 in light. It carries section and field
  labels, so it moves to at least 4.5:1 in both themes, or those labels
  move to `ink-dim`.
- **Code owns it afterwards.** Once adopted, the artifact is re-synced
  from code (`/design-sync`, `editing: "code"`) and its README is the
  contributor reference for UI work; `CONTRIBUTING.md` points at it.
  The UI vitest suite and a light/dark screenshot of the workbench in
  CI are the gate.

## Out of scope for 1.0

Stated so nobody waits on them.

- **LoRaWAN multi-region and TTN.** Safety-sensitive and untestable
  without a non-US915 gateway. The region table design is in
  `docs/lorawan/LORAWAN_TARGET_PLAN.md` (12a); it ships when a gateway
  exists to test it. 1.0 is US915
  and ChirpStack, documented as such.
- **Multi-user and HA replicas.** The studio is a single-user tool with
  one active design per process. A multi-writer backend is 1.x if a
  second user ever appears.
- **Reverse import** (ESPHome YAML to `design.json`). Would make the
  artifact a source, which the architecture rules out.
- **Multi-device projects.** One design, one device.
- **New targets.** Arduino/PlatformIO scaffolds, Zephyr, Zigbee/Thread
  on the C6, Printables search.
- **Component variants (`extends:`).** `aliases` covers the lookup
  case; inheritance waits for a second concrete need.

## Sequencing

The dependency order, not a calendar:

1. 0.40 connectors and 0.41 sugar retirement, since they change the
   model and must precede the freeze.
2. 0.42 migrator, then the schema audit.
3. Per-framework coverage baselines and the MCP conformance test, both
   pure CI, in parallel with 1 and 2.
4. Agent eval harness (in, row promoted; the first scored nightly run
   sets its gate).
5. The flash stage of the hardware gate (written), as soon as the spare
   boards are on a bench; the promote/demote pass follows its first
   green week.
6. Physical outputs and the hygiene list, in any order.
7. Community designs: the catalogue repository and its CI, then
   browse, import and share in the studio.
8. Docs consolidation, last. The `1.0` schema cut is in.
9. The design system: tokens, then components, then the contrast fix,
   once the design session hands the package over. Before the 1.0
   release PR, in parallel with the green week.

The release that carries the schema cut, the two-tier status table,
the upgrade test, the community catalogue and the adopted design system
is 1.0. Phase 4 of the workbench, the JLCPCB order and
the printed enclosure are each welcome before it and not required by it.
