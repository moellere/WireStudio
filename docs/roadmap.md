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
  The fields stay accepted until 1.0 and are rewritten by the migrator.
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
banner, taken from the first covbench run; Meshtastic has none yet, and
its first run on hardware captures the output one is taken from. The LoRaWAN paths are not among the frameworks the stage
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
| wled | 17 |
| lorawan | 26 |

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
- **LoRaWAN** has blocks for the boards' own peripherals and for 21
  sensors: the I2C environment, light, distance, current and motion
  parts, the DS18B20, the ADC parts and the motion detectors, each
  adding named fields to the payload codec. The `lorawan-firmware` gate
  builds designs that carry every block, so a library or API mismatch
  fails the PR that brings it. What remains are the UART and SPI
  sensors, the Modbus meters (a Modbus read in the firmware) and the
  parts with nothing to report.
- **WLED** has both tiers: the runtime one (LED outputs, buttons, IR,
  relay as `cfg.json`) and the compile-in one (a `usermod` block that
  emits a `platformio_override.ini` environment, built by `wled_build`
  and the `wled-firmware` workflow against v0.15.2). Nine sensors carry
  usermod blocks, and the workflow builds a design per usermod on PRs
  that touch a component file; the baseline names the reason for each
  remaining one. When the pin moves to 0.16 the override switches from build
  flags to `custom_usermods`.

Boards: all 26 have an ESPHome example. The enclosure block is on 9.
Section 4 covers the rest.

## 4. Physical outputs

- **PCB.** Backlog, one issue each: routed DRC results in the UI
  (today it is a CI verdict,
  [#344](https://github.com/moellere/WireStudio/issues/344)), route
  parameters for via cost and keepouts
  ([#345](https://github.com/moellere/WireStudio/issues/345)), copper
  pours for the power nets
  ([#346](https://github.com/moellere/WireStudio/issues/346)). An example ordered from JLCPCB and brought up on the
  bench would be the only test of the fab bundle beyond its structural
  checks; it is not a 1.0 gate.
- **Enclosure.** `enclosure:` metadata for every board whose outline
  is published: nine have it. Of the other seventeen, the six M5Stack
  Atoms ship in their own case, the ESP-01 and ESP8285 are modules for
  a host board, and the two camera boards need a lens window in the lid
  that the generator does not cut. The ESP32-C3 and S3 DevKits publish
  their outlines as DXFs on dl.espressif.com, not yet transcribed; the
  S3 and C6 SuperMinis, the Heltec V2 and V4 and the T-Beam wait on a
  published drawing. YAPP_Box is
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
  ([#312](https://github.com/moellere/WireStudio/issues/312)), all but
  the ATOM U. `global_label_dangling` stays in the ERC baseline only for
  onboard parts on GPIOs no header breaks out. After that the
  baseline holds only what KiCad's pin types cannot express (the
  passive-header `pin_not_driven` cases and SPI's shared MISO) and the
  library-table warning a `sym-lib-table` in the image would remove.

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
  too whenever `ANTHROPIC_API_KEY` is set. Claude Code scored 26 and
  25 of 28 on one commit, so `gate.claude_code_min_pass` is 24;
  `gate.min_pass` waits on a first run with an API key. A model swap is
  a dispatched run and a diff of two summaries.
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
  the rows the flash stage decides and the `0.3 → 1.0` step are filled
  in at release.

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
- **Community designs and templates**
  ([#357](https://github.com/moellere/WireStudio/issues/357), from
  @agripnt). A submissions repository that takes designs by pull
  request, checks each one with the studio's own gates and publishes an
  index the studio browses and imports from. It builds on the frozen
  1.0 schema, so it starts after the release.

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
7. Docs consolidation and the `1.0` schema cut, last.

The release that carries the schema cut, the two-tier status table and
the upgrade test is 1.0. Phase 4 of the workbench, the JLCPCB order and
the printed enclosure are each welcome before it and not required by it.
