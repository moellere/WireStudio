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
  / `dht22` / `oled` lower to library components internally (phase A of
  the framework plan in `START.md`), so the Arduino path reads the same
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
| LoRaWAN standalone and external-component paths | the flash stage of the nightly hardware gate (below) | stays *hardware-validated*, labelled as such, no CI claim |
| Remote workbench | same gate, plus the transport tests already there | same |
| Meshtastic flash + config | nightly flash of a radio board, boot verdict by banner once one is established upstream, config read back | demote to *Experimental* |
| CircuitPython flash + code.py | nightly flash, boot verdict by the CIRCUITPY drive enumerating on the bench, `code.py` runs without a traceback on the serial console | demote |
| MicroPython flash + main.py | nightly flash, REPL banner, `main.py` runs without a traceback | demote |
| Component authoring | **promoted.** A user component goes through `esphome config` in the config gate; `tests/test_component_corpus.py` holds the check gate to a corpus of bad components | |
| ESPHome dashboard compile | **promoted.** The nightly `dashboard` job runs a real `esphome dashboard`, open and password-protected, and pushes, compiles and fetches through the studio's client with the wire assumptions asserted | |
| MCP server | **promoted.** `tests/test_mcp_client.py` drives the mounted server with the `mcp` package's client, every PR; the suite itself now runs in CI (`tests.yml`), which no row could claim before | |
| Thingiverse relay | nothing; third-party ranking | stays *Experimental* |
| Agent | the eval harness (section 5), **in**; the first nightly run sets `gate.min_pass`, and the row is promoted once the gate has held it | stays *Experimental* |

### The nightly flash stage (workbench phase 3)

Blocked on one spare board. Every board on the reference bench carries
live traffic, so the gate is non-destructive today. One dedicated
ESP32-S3 (or two: one plain, one radio) turns on `flash: true` for a
representative example per framework, and that single change retires
every "no live-flash gate" caveat at once. It is the highest-leverage
item on this page and the only one a human has to buy hardware for.

Once it runs: the gate flashes one example per framework per night,
reads the boot verdict through `workbench_verify_boot`, and the README
row cites the job. The CronJob stays inside the cluster (a public
repository cannot run fork PRs against a bench), so a failed Job is the
report, as with the existing gate.

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

Boards: all 26 have an ESPHome example. The enclosure block is on 7.
Section 4 covers the rest.

## 4. Physical outputs

- **PCB.** Routed DRC feedback in the UI (today it is a CI verdict),
  via-cost and keepout tuning exposed as route params, copper pours for
  the power nets. One bundled example **ordered from JLCPCB and brought
  up** on the bench, with the order's BOM / CPL / Gerber committed as a
  fixture. That is the only test of the fab bundle that is not a
  structural check; it costs real money and is a 1.0 gate only if the
  owner decides it is.
- **Enclosure.** `enclosure:` metadata for every board whose outline
  and mount holes are published (most of the 19 without one are M5Stack
  units and supermini boards with known dimensions). A lid with
  snap-fit or screw bosses, since a shell with no top is not an
  enclosure. The YAPP_Box question gets decided, not deferred: either
  the generator adopts it as the engine behind the same `.scad`
  endpoint, or the in-house one stays and the decision is recorded.
  One enclosure printed and fitted to its board, photographed in the
  docs.
- **Schematic.** 0.40 draws the sheet itself (board, peripherals,
  subcircuits as blocks, PWR_FLAGs, no-connects) and
  `scripts/check_sch.py` has kicad-cli read every example's netlist back
  from the geometry. Every subcircuit is drawn from its `schematic:`
  layout, and `check_sch.py` fails a layout that leaves a pin to the
  fallback stub. What remains is a `kicad.pin_map` for the twenty
  boards drawn as generic headers
  ([#312](https://github.com/moellere/WireStudio/issues/312)), which
  retires `global_label_dangling` from the ERC baseline. After that the
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
  the job summary; `gate.min_pass` holds the pass count. What remains:
  the first nightly run against the default model records the score,
  `min_pass` is set to it, and the README row is promoted once the gate
  has held. A model swap is then a dispatched run and a diff of two
  summaries.
- **MCP conformance in CI.** The `mcp` client library against the
  mounted server: connect with the token, list tools and resources,
  `create_design` → `add_component` → `solve_pins` → `render`, read
  `design://{id}/yaml`, confirm the `design-changed` event fired. Closes
  the "not run against a live MCP client" caveat.
- **Cost line.** The remaining items from the cost-tuning list in
  `START.md` (compact `search_components` results, `max_iterations`
  at 8) ship behind the eval so a cheaper turn is shown not to cost
  passes.

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
- `START.md` is a 100 KB working log. At 1.0 the decisions it holds
  (locked decisions, the framework axis, the MCP architectural
  principle, the schema) move into `docs/` as short reference pages,
  and `START.md` is reduced to the session-resume block and a pointer.
  The CLAUDE.md convention that cites it moves with it.
- `docs/user_guide.md` gains the paths that landed since it was
  written: inventory, component authoring, the six-framework flash
  dialog, the workbench, both build paths.
- Release notes for 1.0 list the migrations and the tier changes, not
  the features.

## Out of scope for 1.0

Stated so nobody waits on them.

- **LoRaWAN multi-region and TTN.** Safety-sensitive and untestable
  without a non-US915 gateway. The region table design is in
  `START.md`; it ships when a gateway exists to test it. 1.0 is US915
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
4. Agent eval harness (in; the first nightly run sets its gate).
5. The flash stage of the hardware gate, as soon as the spare board is
   on the bench; the promote/demote pass follows its first green week.
6. Physical outputs and the hygiene list, in any order.
7. Docs consolidation and the `1.0` schema cut, last.

The release that carries the schema cut, the two-tier status table and
the upgrade test is 1.0. Phase 4 of the workbench, the JLCPCB order and
the printed enclosure are each welcome before it and not required by it.
