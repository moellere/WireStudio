# Changelog

All notable changes to wirestudio.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed

- **Schema version 0.3: the design fields nothing read.** The audit
  before the 1.0 freeze (roadmap section 1) walked every property in
  `design.schema.json` to its readers. Six had none, so the `0.2 -> 0.3`
  step drops them: `created_at` and `updated_at` (no store maintained
  them; the saved-design list carries its own `saved_at`), `agent`
  (agent sessions live in the session store, never in design.json), and
  `lorawan.chirpstack_application_id`, `device_profile_id`,
  `provisioning` and `dev_eui` (the provision endpoints take the DevEUI
  from the request and the ChirpStack ids from ChirpStack; `compile_time`
  provisioning was never built). Every bundled example and the web UI's
  new designs are at 0.3; 0.1 and 0.2 stay accepted on input and the
  0.1 fixture's golden now ends at 0.3.

### Added

- **Schematic layouts for the LED indicator, both low-side drivers, the
  level shifter, the voltage divider and USB-C power in.** Each is drawn
  as a circuit from a `schematic:` block (rails, the flyback diode across
  the load, the divider with its filter capacitor, the CC pull-downs)
  instead of a column of labelled parts, so every subcircuit in the
  library now has one. `check_sch.py` fails a sheet where a layout leaves
  a pin to the fallback stub.

- **WLED usermods for the BH1750, AHT10, AHT20 and VL53L0X.** The
  BH1750_v2, AHT10_v2 (sensor type set per part) and VL53L0X_gestures
  usermods, each with its library pinned. v0.15.2 includes the BH1750
  header as `usermod_BH1750.h` while the file is `usermod_bh1750.h`, so
  the build links the name it asks for; without it the usermod only
  built on a case-insensitive filesystem. The `wled-firmware` workflow
  now builds one design per usermod a component carries and runs on PRs
  that touch a component file. WLED covers 17 of 102 parts.

- **LoRaWAN blocks for 21 sensors.** The BME280, BMP280, BME680, AHT10
  and AHT20, SHT3x, SHT4x, HTU21D, SCD4x, BH1750, TSL2561, VEML7700,
  VL53L0X, INA219, MPU6050, DS18B20, the ADC, potentiometer and voltage
  divider (scaled by its resistors), and the HC-SR501 and RCWL-0516
  each contribute named payload fields, which the codec decodes and
  announces to Home Assistant. The `lorawan-firmware` workflow now
  builds designs carrying every component with a `lorawan:` block as
  well as the bare boards, and runs on PRs that touch a component file.
  LoRaWAN covers 26 of 102 parts.

- **Tasmota templates for 24 more parts.** Motion sensors and LED
  indicators, low-side drivers, the PWM fan's tach counter, the ADC
  parts, the TM1638, MAX7219 and MAX31855, the RC522, MCP23S17, XPT2046,
  CC1101 and SX127x LoRa on SPI, the RDM6300, GPS, TuyaMCU, PZEM-004T and
  SDM meters (SDM630 when three-phase), the I2S microphone and
  MAX98357A, and the ESP32 camera. A part on a hub maps through the
  hub's bus, and two parts sharing a bus pin with the same function no
  longer warn. Tasmota covers 75 of 102 parts.

- **CircuitPython and MicroPython for Modbus RTU, the PZEM-004T, SDM
  meters, the Tuya MCU bridge and its sensors and switches, and the
  ADS1115 and MCP3008 channels.** Protocol code shared by both
  frameworks: Modbus requests and replies checked by CRC-16, the FLOW
  pin driving an RS485 transceiver; ESPHome's pzemac and sdm_meter
  register maps; the Tuya frames, ESPHome's start-up sequence, the
  heartbeat and datapoint reports, with switches sending datapoint
  delivers and sensors scaled by their `multiply` filters. Both
  generators now pass a hub child its hub as `parent`, render hubs
  before their children, and skip a child with no hub connection.
  Tested against a simulated Modbus slave and Tuya MCU in
  `tests/test_uart_frames.py`.

- **CircuitPython and MicroPython for the I2S microphone and the
  MAX98357A; CircuitPython for the ESP32 camera.** The microphone is a
  level meter over `audiobusio.PDMIn` (PDM mics) on CircuitPython and
  `machine.I2S` (I2S mics, 24-bit samples in 32-bit slots) on
  MicroPython; each framework refuses the variant it cannot read. The
  amplifier plays a half-second 444 Hz tone at start-up through
  `audiobusio.I2SOut` or `machine.I2S`. The camera is `espcamera` with
  ESPHome's DVP wiring, its resolution mapped to a frame size. Both
  generators now read an `i2s` bus's LRCLK and BCLK pins for the parts
  on it instead of dropping the bus, and the library check's synthetic
  design gives that bus clock pins and puts I2S data lines on GPIOs.

- **CircuitPython and MicroPython for the MFRC522; MicroPython for the
  PN532.** Datasheet code following ESPHome's rc522 and pn532: the
  MFRC522's timer and modulation setup, REQA as a 7-bit frame, then
  anticollision and SELECT with a computed CRC_A through each cascade
  level, the antenna switched off between scans; the PN532's I2C frames
  with their length and data checksums, the ACK, the NACK that re-reads
  a response, and an aborted InListPassiveTarget when no card answers.
  Tested against a simulated reader and card in
  `tests/test_register_code.py`.

- **CircuitPython and MicroPython for the XPT2046 and the PCF8574
  character LCD; MicroPython for the MCP23S17.** Datasheet code shared
  by both frameworks, read from ESPHome's components: the XPT2046's
  pressure gate and closest-two-of-three averaging, the HD44780's 4-bit
  entry and row addressing through the PCF8574 backpack, and the
  MCP23S17's HAEN setup and opcode addressing. Tested against fake buses
  in `tests/test_register_code.py`.

- **CircuitPython and MicroPython for the LD2420, RF bridge, Nextion and
  BL0906.** Frame decoders shared by both frameworks, read from
  ESPHome's components: the LD2420's simple-mode text lines and
  energy-mode frames, the EFM8 bridge's received and learned codes
  (each acknowledged), Nextion touch events (setup sends `bkcmd=0` and
  `page 0`, and a `_send` helper ends commands with FF FF FF), and
  BL0906 register reads with the inverted-sum checksum and ESPHome's
  voltage, current, power, frequency and temperature scaling. Tested in
  `tests/test_uart_frames.py`.

- **CircuitPython and MicroPython for the TM1637, TM1638 and CT clamp;
  MicroPython for Wiegand.** Datasheet code shared by both frameworks,
  only the pin access differing: the TM1637's open-drain start/stop,
  LSB-first bytes and ACK clock, and the TM1638's STB-framed commands
  (both showing dashes at the `intensity` param), and the CT clamp's
  RMS about the bias point over `sample_duration`, scaled by the
  `calibration_point` as ESPHome's ct_clamp is. The Wiegand reader
  orders falling edges across D0 and D1 from pin interrupts, ends a
  frame on a 25 ms gap, and decodes 26/34/37-bit tags and 4/8-bit keys
  with ESPHome's parity rules; CircuitPython has no pin interrupts, so
  its baseline says so. `tests/test_pin_protocols.py` decodes the
  recorded waveforms back into the datasheet's command bytes on both
  frameworks. CircuitPython 68 to 71 of 102, MicroPython 66 to 70.

- **CircuitPython and MicroPython for the BMP180, MPU6886, AXP192 and
  HLW8012.** Register and pulse-rate code shared by both frameworks,
  with only the bus access differing: the BMP180's calibration words
  and the datasheet's integer compensation (its divisions floor; the
  worked example gives 15.0C and 69964 Pa), the MPU6886 set up and
  scaled as ESPHome's component does, the AXP192 switching on the
  T-Beam's LoRa and GPS rails and reading the battery as the lorawan
  block does, and the HLW8012/BL0937 power, current and voltage from
  CF/CF1 pulse rates with ESPHome's multipliers. `tests/test_register_code.py`
  runs each framework's setup against a fake I2C bus. CircuitPython 64
  to 68 of 102, MicroPython 62 to 66.

- **CircuitPython and MicroPython for the MH-Z19, CSE7766, RDM6300 and
  LD2410.** Each decodes its UART frame in datasheet code, the same
  decoder text on both frameworks: the MH-Z19 0x86 read with its
  two's-complement checksum (and the 0x79 baseline-calibration command
  from the `automatic_baseline_calibration` param), the CSE7766 24-byte
  coefficient/cycle frame with its overflow and valid flags, the
  RDM6300 ASCII-hex tag frame and its XOR check, and the LD2410 target
  report. `tests/test_uart_frames.py` feeds each framework's decoder
  the MH-Z19 datasheet reply and constructed frames, valid and broken.
  Both generators now pass the bus `parity` to the UART (the CSE7766
  runs 8E1). CircuitPython 60 to 64 of 102, MicroPython 58 to 62.

- **MicroPython for every part with a driver.** 20 more library parts
  carry a `micropython:` block (38 to 58 of 102), the MicroPython side
  of the CircuitPython set: H-bridges (DRV8833 fast/slow decay truth
  table over two PWMs), the ULN2003 stepper (wave, full and half step),
  RTTTL (`upy-rtttl`), MAX7219, ILI9341 (`micropython-ili9341`),
  ST7789 (`st7789py`, its four panel sizes), IR receive and transmit
  (`micropython_ir`; transmit needs the ESP32 RMT, so ESP8266 refuses
  it), SX127x LoRa (micropython-lib `lora-sx127x`), ADS1115 and HX711
  (robert-hh drivers), pulse counters (pin IRQ), voltage dividers
  (`ADC.read_uv`) and the LED and low-side switch parts. The 74HC595,
  PMSx003 frames and UART GPS (checksummed NMEA RMC) are datasheet
  code, tested against a fake `machine`. The MicroPython generator
  gains what the CircuitPython one did: `unsupported(reason)`, buses
  only for parts that rendered, a shared `onewire.OneWire` per 1-Wire
  bus with DS18B20 ROM selection by `address`, and `board` in the
  fragment context. `tests/test_python_blocks.py` runs every block of
  both frameworks for one loop pass.

- **CircuitPython for every part with a bundle driver or a core
  module.** 22 more library parts carry a `circuitpython:` block (38 to
  60 of 102): H-bridges (`adafruit_motor` DC motor), the ULN2003
  stepper, RTTTL, MAX7219 matrices, SSD1306/SH1106, ILI9341 and ST7789
  displays (displayio, with the label on screen), IR receive and
  transmit (`adafruit_irremote`), the 74HC595, SX127x LoRa
  (`adafruit_rfm9x`), ADS1115, HX711, PMSx003, UART GPS, pulse
  counters and PWM fans (`countio`), voltage dividers (`analogio`) and
  the LED and low-side switch parts. A fragment can call
  `unsupported(reason)` for a variant it has no driver for (the
  ILI9481/9486/9488 and ST7796 models, a non-LoRa SX127x), and the
  generator skips that part with the reason and leaves its bus out.
  `tests/test_python_blocks.py` runs every block's generated
  `code.py` for one loop pass against stub modules.

- **MicroPython at the CircuitPython component set.** 22 more library
  parts carry a `micropython:` block (16 to 38 of 102): AHT10/AHT20,
  BH1750, BME680, BMP280, HTU21D, INA219, MAX31855, MCP23008, MCP23017,
  MCP3008, MPU6050, PCA9685, PCF8574/8575, SCD4x, SGP40/41, SHT3x,
  SHT4x, TSL2561, VEML7700, VL53L0X and APA102. Each driver-backed one
  names a permissively licensed driver as a `mip` dep; BH1750, HTU21D,
  MAX31855, MCP3008, PCF857x, SGP4x and APA102 are datasheet register
  code instead, and `tests/test_micropython_registers.py` runs their
  generated `main.py` against a fake bus, checking the bytes written
  and the datasheet's worked examples decoded. 18 more bundled examples
  now generate with no skipped parts. PN532 and MCP23S17 stay in the
  framework baseline with reasons.

- **Upgrade test.** `scripts/check_upgrade.py seed` runs under the
  previous release and writes a data directory through that release's
  own REST API, in both store layouts: every example it bundles saved
  as a design, a user component authored through `/library/components`
  and a design that uses it, inventory rows and an agent session.
  `verify` runs under the checkout and fails unless every design is
  listed and loads at the current schema, renders exactly as its
  original document does when handed to the checkout fresh, and the
  user component, inventory, sessions and SQLite schema versions read
  back. Drift from what the previous release rendered is reported, not
  failed. The `upgrade` workflow runs it from the newest PyPI release on
  every PR that touches the package. Against 0.40.0, whose designs are
  all at schema 0.1, all 75 pass in both layouts.
- **Schema versions for the SQLite stores.** `SqliteDesignStore` and
  `SqliteSessionStore` (`DESIGNS_DB`, `SESSIONS_DB`) record a schema
  version in `PRAGMA user_version` and carry an ordered list of steps,
  which `wirestudio.sqlite_store` runs on open: one transaction per
  step with its version bump, the version read under the write lock so
  two processes opening one file migrate it once. A file written before
  versioning is adopted at version 1 with its rows; a file from a newer
  release is refused with an error naming the store and both versions.
  `python -m wirestudio.sqlite_store version <db>` prints a file's
  version and `backup <db> <dest>` copies it through SQLite's online
  backup, consistent while the studio runs. `docs/deployment.md` gains
  the backup and restore procedure for both store layouts.
- **ESPHome support table.** `docs/esphome-support.md` states which
  ESPHome releases the studio's output validates on: every bundled
  example through `esphome config` on each release of the
  `esphome-matrix` sweep, failures charged to the library components
  ESPHome's error names (the `id` lines in its excerpt, else the
  section's platform, else the whole example marked unattributed), and
  the supported range as the clean run of releases around the pin.
  Today: ESPHome 2026.3 through 2026.9, every example on every release.
  `check_examples.py --json` records a release's verdicts;
  `scripts/esphome_support.py` builds the table from
  `scripts/esphome_support/*.json`, and a test holds the committed
  table to them. The matrix sweeps seven releases, uploads each leg's
  verdicts and merges them in a `table` job. Writing it found the
  gate's own stub API key was all zeros, which ESPHome 2026.9 rejects
  as reserved: every example failed there for that reason alone, and
  the stub is now a fixed non-zero key.
- **`LICENSES.md`.** Every third-party source in the tree or in what
  the studio ships, with its licence: the data derived into the tree
  (Tasmota function ids and chip slot order from `tasmota_template.h`,
  WLED `cfg.json` keys and usermods from v0.15.2, the Meshtastic
  variant map, CircuitPython and MicroPython board ids, the KiCad
  symbol and footprint references at 8.0.0, ESPHome's configuration
  shape), the libraries the generated firmware names and PlatformIO
  fetches at build, the packages Vite compiles into the web bundle,
  what the two Dockerfiles fetch, and what the firmware proxies relay
  without storing. Two facts worth knowing from it: the Meshtastic
  client libraries in the web bundle are GPL-3.0, and a WLED build
  with the BME280 or DHT usermod links GPL-3.0 libraries. The README's
  licence section points at the file.
- **Agent eval harness.** `wirestudio/agent/eval_tasks.yaml` is a fixed
  list of twenty-eight natural-language asks against the bundled
  examples (add a sensor, move one to a new bus, resolve a pin
  conflict, replace a switch with a driver block, swap the board,
  answer a question without editing), each with a tool-call budget and
  a reference solution. `python -m wirestudio.agent.eval` runs them
  against the agent and scores the design it hands back on three
  things: it validates (every pin bound and on the board, no pin
  shared, every bus complete, `esphome config` accepts the render), the
  asked-for change is present, and the turn stayed within budget. The
  run prints a row per task, writes a markdown summary and
  `results.json`, and holds the pass count to `gate.min_pass`.
  `--solutions` replays the reference solutions through the same
  scorer, which proves each task is solvable within its budget without
  a key; `tests/test_agent_eval.py` holds every task to that. The
  `agent-eval` workflow runs the replay on every PR touching the agent
  and the model nightly. Writing the list surfaced two generator gaps
  the `validate` tool does not catch and the scorer does: a WS2812B on
  an ESP8266 defaults to the UART1 method, which only drives GPIO2, and
  a `pwm_fan` instance named `fan` collides with ESPHome's `fan`
  integration id.
- **`write_secrets_stub`** in `wirestudio.validate`: the secrets.yaml
  stub the example gate writes beside a rendered YAML, now in the
  package so the eval harness and the dashboard script share it.
- **WLED target, the usermod tier.** Sensors are WLED usermods,
  compiled into the release with a build flag. A `wled:` block of kind
  `usermod` names the usermod, its define, the libraries its README
  asks for, the compile-time defines its pins and params set, and the
  settings it reads from `cfg.json`'s `um` section. `bme280`, `bmp280`,
  `sht3xd`, `ds18b20` and `dht` carry one. `build_platformio_override`
  emits the `platformio_override.ini` environment that compiles a
  design's usermods into WLED v0.15.2 (extending the release's own
  environment for the chip, in the release's build-flag form);
  `build_cfg` writes the `um` section; `generate` returns both files.
  `wled_build` runs the build the way the lorawan worker does: a
  shallow clone of the release in the firmware cache, the override
  dropped in, `pio run -e wirestudio` streamed, the artifact cached by
  a hash of the override. `POST /wled/compile` streams it, `GET
  /wled/firmware/{job}` serves it, `/wled/compile/status` probes the
  toolchain (PlatformIO, git and node, since WLED bundles its web UI
  at build time). `wled-sensor-strip` is the bundled usermod example
  (a WS2812 strip, a button, a BME280 and a DS18B20 on a DevKitC);
  the `wled-firmware` workflow builds it against the release on every
  PR that touches the target and nightly.
- **WLED target, the runtime tier.** `POST /wled/cfg`, the target seam
  and `python -m wirestudio.targets.wled` emit the hardware section of
  WLED's `cfg.json` from a solved design: LED outputs (`hw.led.ins`,
  with the bus type from the strip's chipset param and the colour order
  from its order param), buttons (a PIR sensor is a button of type 5),
  the IR receiver, the relay and the I2C / SPI pins. A stock WLED
  release image reads that file at boot, so a design made of those
  parts needs no build. Components opt in with a `wled:` block; eight
  carry one (`ws2812b`, `apa102`, `esp32_rmt_led_strip`, `gpio_input`,
  `hc-sr501`, `rcwl-0516`, `remote_receiver`, `gpio_output`). Keys and
  type codes come from `wled00/const.h` and `cfg.cpp`; goldens pin
  `atom-matrix`, `motion-turns-on-light` and `flow-meter`. The coverage
  matrix has a `wled` column; the baseline names the usermod each
  deferred sensor maps to, since sensors are WLED's compile-in tier.
- **Per-framework coverage baselines** (roadmap section 3). The
  coverage matrix now says which generators can use each component:
  a `circuitpython:` / `micropython:` block, or the tasmota / lorawan
  target listing it (Tasmota autodetects I2C parts without a block).
  `scripts/framework_baseline.yaml` carries one reason per missing
  block, of three kinds: `deferred:` names the fragment or template
  rule still to write, `no driver upstream` means the framework's own
  library has nothing to wrap, `no meaning on this framework` means
  the part has no code there at all. `coverage_matrix.py --strict`
  (the esphome-config gate and `tests/test_coverage_baseline.py`)
  fails on an unexplained gap, a stale entry or a reason outside the
  three, and `docs/library-coverage.md` lists every gap under
  "Framework gaps". The starting ledger: circuitpython 64, micropython
  86, tasmota 51 and lorawan 97 gaps out of 102, every one explained.
- **Three "Works" rows promoted to Verified** (roadmap section 2), and
  the test suite in CI. No workflow ran pytest or vitest before: a row
  that cited `tests/test_x.py` cited a file in the tree. `tests.yml`
  runs both on every PR. On top of it:
  - **MCP server.** `tests/test_mcp_client.py` starts the studio under
    uvicorn and drives the mounted server with the `mcp` package's own
    Streamable HTTP client and the bearer token: lists the tools, takes
    a design from `create_design` through `add_component`, `solve_pins`,
    `validate` and `render`, and reads the `design://` and `library://`
    resources. A client without the token is refused.
  - **Component authoring.** `scripts/check_examples.py --component
    draft.yaml` runs a user-authored component through `component_check`
    and its synthetic design through upstream `esphome config`; the
    config gate does so for `tests/fixtures/components/led_driver_npn.yaml`
    on every PR. `tests/fixtures/bad_components/` is a corpus of that
    draft with one defect each and the error the gate must name;
    `tests/test_component_corpus.py` holds the gate to it.
  - **ESPHome dashboard compile.** `scripts/check_dashboard.py` starts
    the pinned `esphome dashboard` on a free port, open and then
    password-protected, and pushes, compiles and fetches one example
    through the studio's `DashboardClient`, asserting the wire
    assumptions the client encodes (`/devices` naming, the xsrf token
    and auth cookie, the compile stream's exit event, `/downloads`).
    The nightly `esphome-compile` workflow runs it as a second job.
- **`design.schema.json` says what each field is for.** The fields the
  audit kept but no generator reads are documented as the design's
  record rather than removed: `power.supply` / `rail_voltage_v` /
  `regulator` (only `budget_ma` feeds the solver), `requirements`,
  `components[].role`, `fleet.tags`, and `description`; `warnings`,
  `esphome_extras`, `params`, `locked_pins`, `module` and `join_eui`
  carry a description too, and `target` says that the Tasmota template
  is an export of an esphome design rather than a target value.
  `buses[].parity`, which the model has carried since the cse7766
  landed, is in the schema at last: `smart-plug` did not validate
  against it. `tests/test_schema.py` now holds every example to the
  schema and the schema's property set to the model's, so the two
  cannot drift again.
- **`wirestudio.migrate`: design.json migrations** (roadmap 0.42). A
  design carries a `schema_version`, and a chain of per-version steps
  brings an older document to the current one before anything reads
  it: the file and SQLite design stores on load, every REST endpoint
  that takes a design and `POST /designs` before it writes, the MCP
  `create_design` tool, and the generate CLI. Each step changes only
  what it is about and leaves the rest of the document as it was, so a
  migrated file diffs as the change it carries. `python -m
  wirestudio.migrate design.json` prints the migrated document,
  `--write` rewrites the file, `--check` exits non-zero when a file is
  behind (the examples are held to it in tests); `wirestudio-migrate`
  is the console script. A document with no version, or one from a
  newer release, is refused with a message that says so rather than a
  validation error on a field that does not exist yet.
- **Schema version 0.2.** The first step, `0.1 -> 0.2`, rewrites the
  deprecated `lorawan.gps` / `dht22` / `oled` blocks into the `uart_gps`,
  `dht` and `ssd1306` components, buses and connections they stood for,
  the same lowering the generators have applied since 0.40. Every
  bundled example and the web UI's new designs are at 0.2; 0.1 stays
  accepted on input. The `1.0` step, which drops the blocks from the
  model, is cut at release.


- **The rest of the connector family, and a netlist golden.** `connector_1x02`,
  `1x05`, `1x06`, `1x07` with the same `family` switch, and
  `connector_2x05_idc`, a shrouded 2x5 box header for a 10-way ribbon.
  Connectors now carry the `J` designator in the schematic, PCB, BOM and
  CPL rather than `U`. `component_check` renders a templated footprint
  once per enum value, as the footprint gate already did, so a `family`
  option that names no footprint fails the check in the studio and not
  only in CI. `python -m wirestudio.kicad.netlist design.json` prints a
  design's netlist one net per line; `actuator-harness` pins it as a
  golden, which is the first test that holds the whole netlist of a
  connector design, not only the pads it asks about.

### Changed

- **The `adc` part's CircuitPython and MicroPython blocks apply its
  `multiply` filters**, so the battery divider a board seeds reads the
  cell voltage there too. MicroPython prints volts (`read_uv`, or
  `read_u16` against 3.3 V where the port has no calibrated read)
  instead of the raw count.

- **Workflow actions on their current majors.** Every action the
  workflows use ran on the Node 20 runtime GitHub deprecated, and each
  job log opened with the warning. `actions/checkout` v4 -> v7,
  `setup-python` v5 -> v7, `cache` v4 -> v6, `upload-artifact` v4 -> v7,
  `download-artifact` v4 -> v8, `setup-node` v4 -> v7, `setup-java`
  v4 -> v6, the five `docker/*` actions one major each and
  `softprops/action-gh-release` v2 -> v3, all on Node 24. Every input
  the workflows pass exists unchanged in the new majors; the one
  behaviour change that applied is `setup-node`'s caching on by
  default, which the WLED build turns off since its `npm install` runs
  inside the release checkout.
- **The LoRaWAN firmware generator and codec read only `components`,
  `buses` and `connections`**, as the ESPHome generator does. The codec's
  synthesized peripherals now come from the board file alone (onboard GPS,
  PMIC, battery divider, OLED); a sensor a design asks for by block
  arrives as a design component with real wiring, so the console-UART
  check looks at the GPS's bus rather than the block. Payload order for a
  design that used a block and an onboard sensor together follows the
  design-then-onboard rule every other design already had (a `dht22`
  block on a T-Beam packs the DHT fields before the GPS and battery);
  re-push the codec after reflashing such a device.

### Deprecated

- **`lorawan.gps`, `lorawan.dht22` and `lorawan.oled`.** The standalone
  path's three sensor blocks predate per-component `lorawan:` codegen;
  each is sugar for the `uart_gps`, `dht` or `ssd1306` component, the
  bus and the connections a user would have added. They are still
  accepted: `targets.lorawan.lower` rewrites a design to those components
  before anything reads it, and `validate` reports each block it lowered
  at info level. The 1.0 migrator rewrites them in `design.json`; add the
  component instead of setting the block (roadmap 0.41).

### Fixed

- **The KiCad install steps time out.** `kicad-render`, `pcb-drc` and
  `pcb-route` install KiCad 8 from its PPA, which can stall mid-install;
  the step now fails after 25 minutes instead of holding the runner for
  the six-hour job default.
- **README status: the release line said v0.35.0 and the MCP row was
  still "Works"** after the row was promoted to Verified in 0.40.0.

- **Tasmota templates on ESP8266 named the wrong functions** for every
  part whose function sits after the first `#ifdef ESP32` block of
  Tasmota's function enum: Wiegand, TM1637, MAX7219, the 74HC595 and
  the LD2410 were written with ESP32 numbers, which an ESP8266 build
  reads as other functions (TM1637 CLK as a plain input). The template
  now uses the ESP8266 build's numbering on ESP8266 boards, and refuses
  ESP32-only functions (the webcam) there with a warning.

- **DS18B20 on a 1-Wire bus in CircuitPython.** The block read a DATA
  pin that a bus-wired sensor does not have, so every example with a
  1-Wire bus skipped it. The generator now emits one `OneWireBus` per
  1-Wire bus, sensors on it share it, and a sensor with an `address`
  param picks that ROM instead of the first one found. The synthetic
  design the component gate renders gives its 1-Wire bus a pin.

- **The `-pcb` and `-full` images had no user component library.**
  `Dockerfile.pcb` never set `LIBRARY_USER_DIR` or created
  `/data/library`, so on those images (the one prod runs among them)
  `component_create` failed with "no user library directory
  configured" and a user component had nowhere to live across
  upgrades. It now matches the default image.

## [0.40.0] — 2026-10-18

### Added

- **Connector components and the `net` connection target.** A
  wire-to-board connector that carries lines belonging to several
  components could not be a library part: every pin had to land on a
  rail, GPIO, bus or expander pin of its own, and a subcircuit's internal
  nets were private to the instance. Pins of `kind: passthrough` and a
  `{kind: net, component_id, net}` target fix that: the position joins
  the net another component's role is wired to, or one of a subcircuit's
  internal nodes (`bridge.out_a`), and the schematic, PCB, BOM and CPL
  put its pad there while the solver, YAML and firmware generators leave
  it alone. `validate` reports a target that resolves to nothing.
  `connector_1x03` / `1x04` / `1x08` ship with a `family` param that
  switches the footprint between JST-XH, JST-PH, a pin header and a
  screw terminal; a component `kicad.footprint` may now be a template
  over the params, and the footprint gate checks every enum value.
  Example `actuator-harness` puts a bridge, a pot and a tach switch on
  one 8-way plug and an encoder and button on a 4-way pigtail;
  `usbc-led-strip` gains the strip's 3-way plug (#300).
- **Enclosure → print-warden handoff.** The Enclosure dialog gains a
  **Print** tab, the API `POST /design/enclosure/print` (with
  `GET /enclosure/print/status` and `GET /enclosure/print/jobs/{id}`),
  and the MCP tools `print_warden_status`, `print_enclosure`,
  `print_job_status`. wirestudio generates the shell, uploads the `.scad`
  to the warden and stages it through the warden's own MCP `submit_job`;
  fit tunables (wall, clearance, standoff height ...) travel as OpenSCAD
  `-D` overrides, so the warden renders and slices exactly what the
  Generate tab downloads. Nothing on this side can start a print: the job
  is offered to the operator's phone or started by the warden's
  `auto_start` policy. Configured with `PRINT_WARDEN_URL` and, when the
  warden has one, `PRINT_WARDEN_TOKEN`; unset leaves the tab explaining
  what to set.
- **wirestudio draws the schematic.** `POST /design/kicad/sch`, the
  **Download schematic** button and the `kicad_sch` tool write a KiCad 8
  `.kicad_sch` directly, and `/design/kicad/render` and `/design/kicad/erc`
  run kicad-cli on that file instead of a SKiDL placement. The sheet is
  built, not solved: the board on the left with every pin labelled,
  flagged no-connect or on a rail symbol, the peripherals in columns
  beside it, each subcircuit as a block, one PWR_FLAG per rail. A
  subcircuit's library entry can carry a `schematic:` layout (part
  placements, wire polylines, ports, in grid units) and is then drawn as
  a circuit, with junctions computed where three things meet; the MOSFET
  H-bridge has the first one and comes out as two legs with the motor
  between them. Pins a layout misses are still labelled, and an internal
  node a connector's `net` target reaches gets a label (at the layout's
  port for it, else at one of its pins), so a partial layout is
  incomplete, never wrong. Symbols are embedded from the pinned
  KiCad library with `extends` resolved, so the file opens with no
  library setup, and output is deterministic down to the UUIDs. The
  render and ERC features now need the symbol libraries on the server
  (`KICAD8_SYMBOL_DIR`) rather than SKiDL; the SKiDL script export and
  its netlist gate stay as they were.
- **`scripts/check_sch.py`.** For every example, kicad-cli reads the
  netlist back from the written sheet's geometry and it is compared with
  the design's: a wire that misses a pin, a label on the wrong net or a
  missing junction shows up as a split or merged group. Runs in the
  `kicad-render` workflow.

### Fixed

- **The board is wired in the schematic and PCB.** The SKiDL script
  placed the dev board's symbol and never connected a pin of it: every
  `GPIO_*` net had one member, the peripheral, and the MCU sat on the
  sheet as an island with the labels floating beside it (the PCB had the
  same gap, documented as a known limitation). Boards drawn with a module
  symbol now carry a `kicad.pin_map` (board role -> symbol pin:
  `GPIO36: SENSOR_VP`, `D2: SDA/D2`, `3V3: VDD`), and
  `netlist.board_bindings` turns the design's gpio, rail and bus
  connections into board pins for both artifacts, buses through the
  bus's own pins or the board's default bus. GPIO nets are declared once
  in the script so the peripheral and the board land on the same net,
  and a role the symbol has no pin for (a module's 5V) is noted in the
  script instead of invented. Covers the ESP32-WROOM-32, ESP-12E and
  WeMos D1 mini symbols; boards drawn as generic headers still float and
  say so.

## [0.39.0] — 2026-10-18

### Added

- **`usb_c_power_in` library component.** A power-only USB-C sink as a
  subcircuit: the 16-pin USB 2.0 receptacle, a 5.1k Rd pull-down on each
  CC line (without them a C-to-C cable from a compliant source never
  turns VBUS on) and a bulk cap, wired VBUS -> 5 V rail, GND -> GND.
  For designs whose load, a motor bridge or an LED strip, should not run
  through the dev board's own USB port. No ESPHome config of its own.
  Example `usbc-led-strip` feeds a WS2812B strip from one.
- **`create_design` MCP tool.** The design-editing tools needed a design
  that already existed in the store, and nothing on the MCP surface could
  put one there: a client with a finished `design.json` had to go through
  the web UI or the REST `POST /designs` behind the browser's SSO.
  `create_design` takes the document, checks it the way `validate` does,
  stores it under its id and makes it the active design. An existing id
  is refused unless `overwrite` is set.
- **Flash size override in the Inspector.** ESP32 boards get a flash size
  select under the board picker: "Board default (NMB)" or 4/8/16/32 MB,
  writing `board.flash_size_mb`. Raising it above the board file's value
  shows an inline boot-loop caution, matching the
  `flash_size_override_above_board` warning (#219).

### Fixed

- **Switching boards in the web UI drops `board.flash_size_mb`**, as the
  agent's `set_board` already did. A size measured on one board was being
  carried to the next.

## [0.38.0] — 2026-10-03

### Added

- **MCP23S17 and MCP3008 library components.** `mcp23s17` is the SPI
  sibling of the MCP23017: same sixteen GPIOs, same `mcp23xxx:` pin
  discriminator on downstream platforms, a `deviceaddress` param for the
  A0-A2 hardware address, and its own CS. `mcp3008` is an 8-channel
  10-bit SPI ADC hub with a VREF pin, read through `mcp3008_channel`
  instances (channel number, reference voltage, update interval) the
  same way `ads1115_channel` hangs off `ads1115`. Example `spi-io-node`
  puts both on one SPI bus.

## [0.37.0] — 2026-09-26

### Added

- **Boot output and verdict in the flash dialog after a slot flash**
  (workbench phase 2, client half). Flashing a bench slot used to end at
  "written": the bench owns the port, so the dialog had no serial to
  show and the roadmap's "still to do" stood since 0.29. Now the dialog
  relays the slot's recorder for twenty seconds after the flash and
  asks the bench for its boot verdict: booted, with the line that proved
  it; no marker within the framework's timeout; or why the framework
  cannot be verified (CircuitPython enumerates a drive, Meshtastic has no
  established banner). `GET /workbench/slots/{slot}/output` and
  `POST /workbench/verify-boot` carry it; `workbench_verify_boot` on
  MCP was already there.

- **ERC on the generated schematics.** The `kicad-render` job now runs
  `kicad-cli sch erc` on the rendered schematics of representative
  examples (`scripts/check_erc.py`). Every violation type ERC reports
  must be listed in `scripts/erc_baseline.yaml` with the reason the
  generator cannot avoid it; today that is five types: undriven
  power-input pins (no PWR_FLAG symbols are emitted), open and undriven
  pins on the bare module symbol and the passive generic headers,
  single-ended global labels from SKiDL's placer, and the library-table
  warning kicad-cli raises without a sym-lib-table. An entry no example
  raises any more fails the run, so the baseline shrinks as the
  generator improves. Anything else, an output driving an output, two
  drivers on one net, fails the PR. `POST /design/kicad/erc` (and `/erc/status`) run the same
  check on demand; `python -m wirestudio.kicad.erc design.json` prints
  it.
- **Substitutes are ranked, and all of them can be accepted at once.**
  A short semiconductor's proposals now come ordered: a known-matching
  pinout and package first, then no marginal rating (under 20% headroom
  on voltage or current, which is added to the caveats), then quantity
  on hand; each carries `headroom` (candidate rating over the circuit's
  need) and its `rank`. *Use all suggested substitutes* in the inventory
  dialog, `POST /design/inventory/apply-substitutions` and the
  `apply_substitutions` MCP tool set `part_overrides` to the best-ranked
  proposal on every short line in one step and report what was applied
  with its caveats; lines without a proposal and design passives are
  left alone, and `set_part_override` still picks or undoes one.

## [0.36.0] — 2026-09-21

### Added

- **A bearer token for the REST surface.** `WIRESTUDIO_API_TOKEN` gates
  every route but `/health` and `/mcp` (which keeps its own token); a
  request presents it as `Authorization: Bearer` or, for the browser's
  EventSource on the SSE routes, as the `wirestudio_api_token` cookie
  the web UI sets for itself. Unset, the API stays open as before, so
  the dev loop and the docker quickstart are unchanged. The web UI asks
  for the token when the API answers 401 and keeps it in the browser;
  Settings shows and clears it. The roadmap's standing caveat that
  `/workbench/flash` and `/lorawan/provision` were reachable by
  anything that could route to the pod is closed, and an ingress can
  publish the whole API rather than `/mcp` alone. `create_app` takes
  `api_token=` for tests; the Kubernetes manifest reads the `api-token`
  key of `wirestudio-secrets` when present.

- **MicroPython target.** The last framework on the backlog, the
  CircuitPython pattern applied upstream. `GET /micropython/firmware`
  proxies the newest stable micropython.org image for the board's chip
  (every library board maps to a generic port image, ESP8266 included;
  the version is read off the board's download page since the site has
  no index API) with the flash offset in a header, 0x1000 on the classic
  ESP32. `POST /micropython/code` generates `main.py` from the design
  over the `machine` API: sixteen components carry a `micropython:`
  block, buses are `SoftI2C` / `SoftSPI` so one file runs on every port,
  and drivers outside the firmware are listed as `mip` specs. The flash
  dialog gains the framework and, after flashing, pushes the file through
  the raw REPL over the same serial port (or to any connected board), so
  nothing is copied by hand. The workbench boot check knows the
  MicroPython banner. Unmapped components degrade to a comment.

### Fixed

- **The ESPHome dashboard client now matches the dashboard.** 0.35.0
  shipped it against an unverified wire format; running it against
  `esphome dashboard` 2026.6.5 found four gaps. `/devices` names a
  config by `configuration`, not `filename`, so every push reported
  `created`. A password-protected dashboard xsrf-checks its login form
  and every POST, so login failed with HTTP 403; the client now takes
  the `_xsrf` token from the login page and sends it as `X-XSRFToken`.
  The compile websocket is authenticated too, so a protected dashboard
  closed it before the spawn; the session cookie now rides the
  connection. ESP32 builds ship `firmware.factory.bin` and
  `firmware.ota.bin` (ESP8266 `firmware.bin`), never `firmware.bin` on
  ESP32; the client reads `/downloads` and picks the OTA or factory
  entry. A dashboard that redirects to `/login` is reported as needing
  credentials rather than as "HTTP 302".

## [0.35.0] — 2026-09-20

### Added

- **Compile through an ESPHome dashboard** (roadmap item 8, the plain
  ESPHome half). `ESPHOME_DASHBOARD_URL` points the studio at the HA
  add-on (port exposed) or a standalone dashboard; the push dialog
  gains a build-path switch and defaults to whichever of fleet or
  dashboard is configured. The studio writes the YAML through the
  dashboard's editor endpoint, starts a compile over its websocket --
  the dashboard dispatches to its own workers -- buffers the log as an
  in-process job, and serves it through `/esphome/jobs/{run_id}`
  (status, incremental log, SSE stream, firmware), the same shapes as
  the fleet routes. `esphome_dashboard_status` / `_push` /
  `_job_status` / `_job_log` join the MCP hardware tools. The four wire
  assumptions live in one module. Adds `websockets`.

- **Superseded tool results are trimmed within an agent turn.** A turn
  that renders, edits and renders again used to carry every render's
  full YAML and ASCII to each later API call. Before each call the
  agent now replaces a read-only tool's earlier result with a one-line
  digest when a later call with the same input supersedes it (render,
  validate, the KiCad and fab tools, search, recommend, library_detail,
  component_check); the latest stays verbatim and mutating tools are
  never touched. A three-render turn sends under half the context it
  did. Persisted history was already text-only and is unchanged.

- **SQLite-backed design and session stores.** `DESIGNS_DB` /
  `SESSIONS_DB` point the studio at one SQLite file each instead of the
  JSON / JSONL directories, for a deployment that would rather back up
  a database or run replicas on shared storage. Same protocols, same
  behaviour (the parity tests run both backends); the file stores stay
  the default. Also: a test that an Anthropic 429 surfaces as an agent
  error event once the SDK gives up retrying.

- **Meshtastic configuration from the flash dialog.** After flashing
  the factory image (or against any node already on a serial port),
  the dialog pushes region, modem preset, owner names and the primary
  channel as protobufs through `@meshtastic/core` over
  `@meshtastic/transport-web-serial`. The flash session now hands its
  WebSerial port back (`FlashSession.release`) so the client reuses it
  without a second port picker. The channel key is generated or pasted
  in the dialog and goes to the device only -- never into the design.
  Defaults come from the design: the device name, and a LoRaWAN region
  mapped to its Meshtastic counterpart. The client loads on demand, so
  the rest of the studio does not carry it.

- **Blocks declare the electrical rules they are held to** (#274). A
  component may carry `verify.checks`: `led_current`, `base_drive`,
  `gate_drive` and `divider`, each one line of arithmetic over the
  block's stated assumptions (Vf, hFE, Vgs(on), Rds(on)) and the
  instance's params, printed with the numbers it used. `component_check`
  runs them at the block's defaults and lists passes under `verified`
  (a block whose defaults fail its own rule is an error); `validate`
  runs them per instance with the real params and the rails it is
  wired to, warning on a failure. A rule that needs a rail only a design
  knows reports as not evaluated rather than passing. The five building
  blocks and `hbridge_mosfet` declare theirs, and `not_checked` now
  says per block what lies beyond them: nothing is simulated.

- **Components can be authored in the studio** (#272, first slice). The
  Components tab gets *New component*; a component's inspector card
  gets *Edit YAML* / *Delete* for a user component and *Copy as new* for
  a bundled one. All three open an editor whose *Check* runs the same
  gate `component_check` runs and whose *Create* / *Save* writes into
  the user library. Listings carry `source` (`bundled` / `user`) and
  the sidebar badges user components. `GET
  /library/components/{id}/yaml` returns a component's source and
  `DELETE /library/components/{id}` removes a user one (409 on a
  bundled id); `component_delete` joins the MCP and agent tools.

- **Subcircuit part values can be parametric** (#272). A part's
  `kicad.value` may be a Jinja template over the instance params
  (`"{{ params.r_led }}"`, with the default in `params_schema`), so one
  block covers a 5 mA indicator and a 20 mA LED. `placed_parts` renders
  it per instance for the schematic, PCB, BOM, CPL and inventory
  check; the recommender and `component_check` render it with the
  defaults, and the check fails a template that does not.

- **Five discrete building blocks** (#272): `led_indicator`,
  `npn_low_side_driver`, `mosfet_low_side_driver`, `voltage_divider`
  and `level_shifter`, each a checked subcircuit with `requires:` on
  its semiconductors and parametric resistor values, so the agent
  composes a driver or a sense input from blocks that already pass
  the gate instead of authoring one from scratch. The `bench-io`
  example puts all five on one board and pins their YAML and BOM.

- **Substitutions can be accepted, not only proposed** (#271). A design
  carries `part_overrides` (`"<component id>.<part id>" -> MPN`); the
  schematic, PCB, BOM, CPL and the inventory check all read the
  override through `placed_parts`, so accepting an IRF9540 for the
  bridge's high side changes what every fab output prints. Only the
  value changes: symbol and footprint stay, which is what same-package
  substitution means. `validate` records each override as an info line
  naming both parts and what the drawer comparison never covered, and
  warns on a key that names nothing. Check lines now carry `keys` and
  `substituted_for`; the check dialog gets a *Use for Q1, Q4* button on
  each proposal; `set_part_override` lands on the MCP and agent tool
  surfaces.

- **Pick list and buy list on the inventory check** (#271). The check
  report gains `pick_list`: everything to pull, grouped by drawer
  location, then stock with no location recorded, then common values
  nobody inventories, then what is missing. A component built from a
  subcircuit is covered by its parts and not listed twice; connectors
  are not stock and are left out. `POST /design/buy-list` and the
  `buy_list` MCP tool price the check's shortfalls on JLCPCB -- a
  component by library id, a semiconductor by MPN, a passive by value
  and family -- and still list the shortfalls, unpriced, when the parts
  API is down. Both show on the inventory dialog.

### Changed

- **The web bundle is built on the build platform.** The image's
  web-builder stage now runs under `--platform=$BUILDPLATFORM`: the
  bundle is the same bytes for every target, and building it natively
  instead of under QEMU takes the arm64 image build from tens of
  minutes on a cold npm cache to the amd64 time.

### Fixed

- **A created component now appears in `/library/components` without a
  restart.** The summary list was computed once at startup on the
  assumption the library never changes; it is now rebuilt when the
  user tree changes (`Library.version`), so `component_create` and the
  sidebar agree.

## [0.34.0] — 2026-09-20

### Changed

- **HANDOFF.md bench table refreshed.** The bench was re-enumerated on
  2026-09-13: the Heltec V4 is on SLOT14 with its L76K seated (antenna
  open, fix intermittent), the TTGO LoRa32 v2 is back on SLOT31, and the
  Heltec V2 joins under its roboat identity. Next-steps updated to match.
- **ESPHome pin bumped 2025.12.7 -> 2026.6.5** (config gate, nightly
  compile smoke, matrix, README/CONTRIBUTING). Two schema breaks:
  2026.x reserves the id `spi0` internally, so the nine examples whose
  SPI bus was named `spi0` rename it to `spi_bus`; and the i2s_audio
  media_player was removed upstream, so the max98357a template now
  emits an i2s_audio speaker wrapped by the speaker media_player
  (goldens regenerated). All 68 examples validate under the new pin.

### Added

- **Components can be authored and checked at runtime** (#263, last
  phase). `component_check` takes a component YAML and reports what a
  reviewer would otherwise eyeball: the file validates against the
  library model, subcircuit part ids are unique and every internal net
  is touched by at least two pins, every pin role reaches a part, the
  ESPHome template parses and renders against a synthetic design (bus
  pins tried on a bus and as bare GPIOs), and -- when the KiCad
  libraries are installed -- every symbol, symbol pin name and
  footprint it names exists. Every report ends with what could not be
  verified here and what is never checked: nothing is simulated.
  Every bundled component passes the same gate, which is the test.

  `component_create` runs the check and saves the text verbatim into a
  user library (`LIBRARY_USER_DIR`, `/data/library` in the image) that
  loads alongside the bundled one; a bundled id always wins, so a user
  file cannot shadow a shipped component. Exposed as MCP and in-studio
  agent tools and as `POST /library/components/check` and
  `POST /library/components`.

- **The inventory check proposes substitutes, and the recommender
  counts drawer parts** (#263 items 4 and 5). A `need` or `partial`
  semiconductor on the parts report now carries `substitutes`: drawer
  parts of the same family, polarity and package (read off the board
  footprint) whose voltage and current ratings clear what the circuit
  asks. The ask comes from a new optional `requires:` block on a
  subcircuit part (`family`, `polarity`, `v_min`, `i_min`) -- the
  circuit's need, not the fitted part's rating, so an IRF9540 at 19 A
  stands in for an IRF4905 in a 1 A bridge. Without `requires:` the
  original part's own drawer rating is the bar, and the proposal says
  so. Every proposal lists what was not compared (gate threshold,
  Rds(on), gain, a differing pinout); nothing is applied. A candidate
  with no recorded rating fails rather than passes.

  `recommend` used to give a flat boost only to components held as a
  unit. A subcircuit component now earns that boost scaled by the
  fraction of its discrete parts the drawer covers (`parts_on_hand` /
  `parts_total`, common passives assumed), so a bridge you have the
  FETs for outranks one you would order for. The inventory dialog's
  check lists the parts report with proposals under each short line.

- **The inventory check sees discrete parts** (#263 item 3). It used to
  group a design into library components and modules only, so the
  fifteen parts an `hbridge_mosfet` puts on the board were invisible to
  it. The report now carries a `parts` section covering subcircuit
  expansions and the design's own `passives`: semiconductors match an
  inventory part by MPN, passives by magnitude, so `0.1uF` in the
  drawer satisfies a `100nF` on the board and `10k` / `10K` / `10000`
  are one resistor. Which one a part is comes from its reference
  designator rather than a guess at its value.

  Two statuses beyond have/partial/need, because the alternative is a
  report nobody reads: a common passive value (E12 resistors, the usual
  capacitors) reports `assumed` rather than `need` -- nobody
  inventories 10k resistors -- and a designator the drawer doesn't
  track, like a motor connector, reports `untracked`. Both stay
  distinct from `have` so the distinction is visible. Surfaced on
  `POST /design/inventory/check` and the `inventory_check` MCP tool.

- **The inspector shows what a subcircuit expands into.** A component
  carrying a `subcircuit:` block (the H-bridges from #262) puts a
  dozen-plus designators on the board, and the inspector showed one
  line for all of them. `POST /design/parts` returns the same
  `placed_parts` expansion the schematic, PCB, BOM and CPL use -- so
  the panel cannot drift from the fab outputs -- and the component
  inspector lists its parts with the designators they carry. It goes
  through the server because refs are design-global: adding a
  component upstream renumbers everything after it.

- **Inventory accepts discrete parts, not only library components**
  (#263, first slice). A drawer is mostly things with no
  `library/components/<id>.yaml`: transistors, MOSFETs, passives,
  regulators. Inventory entries gain a `part` kind whose identity is an
  MPN, carrying typed specs (`family`, `polarity`, `package`, `pinout`,
  `value`, `v_max`, `i_max`). Parts key under `part:<mpn>`, so a drawer
  part named `adc` cannot shadow the `adc` component; existing
  `inventory.json` files load unchanged.
- **CSV import keeps every row.** It finds the header wherever it
  starts (a real export has summary rows above it), maps the column
  names people actually use (Part, Family, Polarity / Type, Total Qty,
  Package, Pinout, Kit Locations, Notes), normalises families and
  polarities, and lifts a leading `55V, 110A` out of a spec note into
  `v_max` / `i_max`. Anything it cannot use comes back in `rejected`
  with a row number and a reason -- previously unknown rows were
  dropped silently. `POST /inventory/import` now reports
  `imported / updated / rejected / header_row`, and
  `PUT|DELETE /inventory/parts/{mpn}` manage parts directly.
- **Inventory on the MCP surface**: `inventory_list`, `inventory_set`,
  `inventory_import` and `inventory_check`. The REST routes sit behind
  SSO in production, so this is the only way a headless client can push
  a drawer into the studio.

- **Library subcircuits.** A component can now be built from discrete
  parts: a `subcircuit:` block lists parts (symbol, footprint, value,
  ref prefix) and wires their pins to nets. A net named after one of
  the component's pin roles joins that role's design connection; any
  other name is private to the instance. The expansion lives in
  `kicad/netlist.py` (`placed_parts`), so the SKiDL schematic, the
  `.kicad_pcb`, the BOM and the CPL all emit the same parts, designators
  and nets. Everything else still sees one component. The footprint
  gate checks subcircuit footprints too.
- **`hbridge` and `hbridge_mosfet` components.** `hbridge` is one
  channel of any two-input bridge (DRV8833, TB6612, L298N, a relay
  pair): `expose: none` emits two outputs for a control loop to drive,
  `switches` two interlocked forward/reverse switches, `fan` ESPHome's
  hbridge fan on PWM outputs. `hbridge_mosfet` is the same interface as
  a discrete 5 V bridge (IRF4905 + IRFZ44N per leg, one 2N3904 driving
  the shared gate node) and is the first subcircuit component. New
  examples `motor-position` and `vent-damper` cover both.
- **Display content intent: `params.show`.** Adding a display used to
  produce a dark panel unless the user hand-wrote the ESPHome lambda.
  `show` is a declarative widget list (text / value / time) lowered to
  the display lambda per dialect: pixel displays (ssd1306, ili9xxx,
  st7789) get an automatic `font:` block (gfonts://Roboto) and
  y-stepped printf lines, character LCDs print into rows, digit
  displays (tm1637, max7219) render one value. Value widgets bind
  other components' readings by id convention (`<component>` for
  single-value sensors, `<component>_<channel>` for multi-channel --
  20 sensor templates now emit those ids); time widgets bring their
  own `time:` block. A hand-written `lambda_` still wins. Validation
  warns on unknown sources/channels/widgets
  (`show_*` codes); the oled example now uses `show` end to end.
- **Named RTTTL melodies for the buzzer.** The rtttl component gains a
  capability (`play` / `stop`), and a play action can name a curated
  melody -- `args: {song: "doorbell"}` -- instead of hand-writing an
  RTTTL string (`args: {rtttl: ...}` stays as the escape hatch). Eight
  reviewed melodies ship (beep, two_beep, success, failure, alarm,
  doorbell, nokia, mario), listed at `GET /intent/melodies`; unknown
  songs warn and the action is dropped rather than emitting a broken
  play. The co2-display example gains a buzzer that plays the alarm
  melody when CO2 crosses 1200ppm (`on_value_range` on the new mhz19
  co2 channel).
- **CircuitPython code.py generation from the design.** The
  LoRaWAN-fragment pattern applied to Python: 36 library components
  gain a `circuitpython:` block -- explicit import lines, Adafruit
  bundle deps, and Jinja2 setup/loop fragments -- and the new
  generator (`wirestudio/generate/circuitpython_gen.py`) resolves the
  design's buses to busio objects, renders each component's wiring
  through the P() pin helper (IO/GPIO/D naming varies per build),
  assembles one runnable file, and ast-validates it. Components
  without a mapping degrade to a warning comment, and only buses a
  mapped component uses are emitted. `POST /circuitpython/code`
  returns {code, deps, warnings}; the flash dialog now prefers
  design-generated code over the board starter and lists the bundle
  libraries to copy to CIRCUITPY/lib plus any unmapped components.
  Every bundled example generates parseable code.

- **Tasmota coverage for the library-sweep components.** Eight new
  entries in the verified FUNC table (values recomputed from
  `tasmota_template.h` enum indexes, anchors cross-checked against the
  existing table): TM1637 CLK/DIO, MH-Z19 and PMS5003 Tx/Rx, Wiegand
  D0/D1, LD2410 Tx/Rx, SN74HC595 Shift595 SER/SRCLK/RCLK/OE, and
  ADC_CT_POWER for the CT clamp; the servo maps its pin to PWM. UART
  parts map through the bus block like CSE7766. MicroPython added to
  the target backlog (after Meshtastic config push and full
  CircuitPython codegen).

### Fixed

- **Tasmota templates put ESP8266 D-labeled pins in the right slots.**
  `D1` used to parse as GPIO1; it is GPIO5. The D0-D8/RX/TX/A0
  convention now resolves to real GPIO numbers, fixing every D1
  Mini / NodeMCU design's template.
- **A component with two connections to one UART bus (TX and RX roles)
  mapped the bus pins twice**, leaving spurious "already assigned"
  warnings on the template.

- **Library sweep: 18 new components** (65 -> 83), drawn from the
  maintainer fleet's real device configs plus the most-requested
  ESPHome hardware, each validated end-to-end through upstream
  `esphome config`:
  - *Environment:* SHT4x, SCD4x true CO2, SGP4x VOC/NOx index,
    VEML7700 lux, BME680, MH-Z19 (UART), PMS5003/PMSX003 particulate
    (UART).
  - *Presence:* LD2410 mmWave (UART, richer channel set than the
    existing LD2420; the stale `ld2410` alias moved off the ld2420
    entry).
  - *Power:* INA219 DC current/power, PZEM-004T v3 AC meter (rides the
    modbus hub like sdm_meter), SCT-013 CT clamp (adc + ct_clamp with
    burden/bias passives modeled).
  - *Input:* PN532 NFC (I2C), Wiegand keypad/reader, IR receiver
    (remote_receiver, with a Tasmota IRrecv mapping).
  - *Output:* TM1637 7-segment display, hobby servo (per-chip
    ledc/esp8266_pwm output plus an HA position slider), PCA9685 16ch
    PWM, SN74HC595 shift register as a first-class expander
    (`expander_pin_key`; downstream components wire to its pins).
- **Six new bundled examples** covering all 18: air-quality-station,
  co2-display (MH-Z19 driving a TM1637 readout), presence-media-node,
  energy-monitor (PZEM-004T + CT clamp + INA219), access-panel (PN532 +
  Wiegand + servo latch), output-hub (PCA9685 + shift-register relay on
  an expander pin). The mhz19/scd4x templates give their CO2 channel a
  referenceable id (`<id>_co2`) so displays and automations can read it.

- **Provisioning records which slot a device sits in.** A LoRaWAN device
  registered through the workbench path is now tagged `slot: SLOT19` in
  ChirpStack, written by the one action that knows the board and the slot
  at the same moment. Until now the only slot-to-DevEUI map was the
  hardware gate's hand-maintained roster, and it went stale silently the
  first time a board was repurposed: the board kept uplinking under its
  new identity while the gate watched the retired one and reported dead
  hardware for four nightly runs. Tags are merged, not replaced, so a tag
  someone else set survives; a device reprovisioned onto another slot
  carries the new slot with it. `ListDevices` returns tags inline, so
  "which device is in SLOT19?" is one call.
- **`Slot.group` / `Slot.role`** are now parsed from the bench. The
  workbench has always reported them and the client dropped them on the
  floor. Slot labels are positional and say nothing about purpose, so
  without these a slot's contents can only be identified by asking
  someone who remembers.

## [0.33.1] — 2026-08-30

### Changed

- **`lorawan-for-esphome` pin moved to the #10 squash-merge on `main`**
  (`b7da6174`). The previous pin was the PR's branch-head SHA, which
  fell off-history when the PR squash-merged; GitHub keeps such commits
  fetchable via PR refs for now, but a pin on main's history is the
  durable choice. Generated YAML changes only in the ref string.

## [0.33.0] — 2026-08-30

### Added

- **`board.flash_size_mb` in `design.json`: a per-design override of the
  library board file's flash size.** Board files pin the *floor* for
  boards sold in several sizes under one name -- the ESP32-S3-DevKitC-1
  ships as N8/N8R2/N8R8 (8MB) and N32R16V (32MB) -- because
  over-declaring boot-loops the board and no static value is right for
  every unit. That left an N32R16V owner with three quarters of their
  flash unreachable and no way to claim it short of editing the shared
  library. The override wins over the board file in both the ESPHome and
  the LoRaWAN generator, is restricted to the sizes both can name a
  partition table for (4/8/16/32), warns
  (`flash_size_override_above_board`) when it raises the board file's
  value since that is the direction that bricks, and is dropped when
  `set_board` switches boards -- a size measured on one board says
  nothing about another. Closes the last actionable half of #219; the
  remaining half is `esptool flash-id` on four boards not at the bench.
- `HANDOFF.md`: current backlog and bench state for picking this up in a
  fresh session -- what is shipped, what is blocked on hardware at the
  bench, which beliefs are unverified, and the gotchas that cost time.
  It had been parked in an unrelated repo, where a session opened on that
  tree could not act on any of it.

### Removed

- **`board.pinned_esphome_version` in `design.json`.** Declared in the
  0.1 schema sketch and never wired to anything -- no generator, API,
  or gate has ever read it, so a design that set it got the same YAML
  built against the same ESPHome as one that didn't. ESPHome version
  pinning is real, but it lives in CI and the container images, not
  per design. Dropped from the model, the JSON schema, the three
  bundled examples that carried it, and the `START.md` schema sketch.
  `design.json` rejects unknown keys, so a design still carrying the
  line needs it deleted; nothing else changes, since nothing consumed
  the value.

### Fixed

- **Heltec V4 FEM: `PA_TX_EN` is per-transfer, not static.** Holding the
  GC1109's PA_TX_EN (GPIO46) high pinned the PA output stage on and left
  the receiver deaf -- 69 join-requests accepted server-side, zero
  join-accepts heard (RadioLib -1116). The board file and both firmware
  paths now drive it through RadioLib's rf-switch (`txen`), with VFEM
  (GPIO7) and CSD (GPIO2) static high and VEXT (GPIO36) static low;
  without VEXT the FEM path is unpowered and TX is leakage-grade
  (-52 dBm at 2 m). OTAA join and a Class C downlink validated on the
  bench. On a V4.3 (KCT8103L) that is still deaf, move `txen` to GPIO5.
- **Heltec V4 GNSS UART direction was backwards.** Heltec's GNSS_TX/RX
  net names are direction-ambiguous, and the Meshtastic-derived table
  0.24.1 cited when it added the auto-wiring has them reversed. Measured
  against a live L76K: the *module's* TX is GPIO39 (the MCU reads NMEA
  there) and its RX is GPIO38.
- **Heltec V4 GNSS stayed mute until standby was driven.** STANDBY
  (GPIO40) undriven leaves the module silent with its TX held low, which
  reads as a UART break flood and is easily mistaken for a floating pin.
  `uart_gps` now carries `standby_pin` and `reset_pin` through the seed
  into both firmware paths, and the power-up order is pinned: VEXT(36
  low) -> settle -> EN(34 low) -> RST(42 high) -> WAKE(40 high) -> ~1 s
  warmup, giving 1 Hz multi-constellation NMEA at 9600. (V4-R8 moves EN
  to GPIO42 and drops reset.)
- **`$GPTXT ... ANTENNA OPEN` on the V4 GNSS is benign**, and this
  bring-up chased it as a fault. The L76K's antenna is an integrated
  passive patch -- there is nothing to connect -- so its active-antenna
  DC-detect always reports open. Noted in the board file. Zero satellites
  indoors is also normal; a first fix needs sky view.
- **The roadmap contradicted itself on why the hardware gate is a
  CronJob.** `docs/index.md` still described phase 3 as carrying "a
  self-hosted runner as real setup and maintenance cost" while
  `docs/workbench.md` explained why a runner was rejected: this is a
  public repository, `pull_request` runs fork-authored workflows by
  design, and a runner reaching the bench network would let any fork's
  PR execute code there. Of everything in that phase it is the decision
  most worth getting right in writing, and the repo argued both sides.
- The same section claimed phase 3 retires the "no live-flash gate"
  caveats. It does not yet -- the flashing half is deliberately off for
  want of a dedicated board, so the caveats still stand. Marked phases
  2 and 3 as shipped, which they have been since 0.29.0 and 0.30.0.

## [0.32.0] — 2026-08-25

### Added

- **`fix_age_min` on every GPS payload.** The position is deliberately
  never cleared when the fix drops -- on a vehicle "where was it last
  seen" is the whole point, and a machine parked with its GNSS off should
  still report where it is. But then nothing distinguished a live fix from
  a week-old one, so the age of the position now rides alongside it.
  65535 is the sentinel for "never had a fix": without the `isValid()`
  guard an unfixed device reports age 0, reading as perfectly fresh, which
  is the confusion the field exists to end.
- This is a **breaking payload change for any design carrying a GPS**.
  The field sits after `sats`, so everything downstream of it shifts by
  two bytes and existing devices need a rebuild, reflash and profile
  update before their uplinks decode correctly again. The T-Beam example
  goes 22 -> 24 bytes, still inside DR1's 53-byte cap, so it costs no
  range.
- **`t-beam-lorawan` example.** A T-Beam uplinking GPS position, cell
  voltage and DHT22 temperature/humidity, with an SSD1306 showing live
  status. The only standalone-LoRaWAN example so far was a bare board;
  this one exercises sensors the board file knows nothing about
  alongside the two it does.
- The cell voltage comes from the onboard AXP192, not an ADC divider:
  `ttgo-t-beam` declares no `battery_adc`, and the codec already refuses
  to synthesize one when a PMIC is present, since both would collide on
  `batt_mv`.
- The design carries no radio component. The board file owns the SX1276
  wiring and `lorawan.region` drives the frequency, so the 433 MHz
  `sx127x` the ESPHome T-Beam example carries would be a false statement
  on a US915 device.

### Fixed

- **A merged image for the classic ESP32 was mistaken for a bare app.**
  `is_merged_image` required the ESP image magic at byte 0, but only the
  ESP32-S3/C3 family puts its bootloader there -- on the classic ESP32 it
  sits at 0x1000, so the image opens with 4 KiB of 0xff erase padding.
  The sniffer read that as "not merged" and would have written the whole
  image to the app offset: the exact bricking case it exists to prevent,
  one chip family over. Caught while flashing a T-Beam.
- **Re-provisioning left an existing device on its old ChirpStack
  profile.** `create_device` treated a known DevEUI as a no-op, so a
  design whose sensor set changed got a correct new profile that nothing
  pointed at, while the caller reported the new profile id -- success for
  a device decoding every uplink at the wrong byte offsets. Seen on a
  real T-Beam, where `batt_mv` was reading the temperature. The device is
  now re-pointed, and the fetched message is handed back to `UpdateDevice`
  so its other fields survive.

## [0.31.0] — 2026-08-25

### Added

- The hardware gate roster accepts `on_bench: false` for a device that is
  powered and transmitting but whose USB cable is out. It is dropped from
  the slots and serial stages and asserted over the radio only. Failing
  every night on a condition everyone already knows about is how a gate
  gets muted, which `docs/workbench.md` warns about explicitly.
- The slots stage now reports a present slot that no roster entry claims.
  That is the same class of divergence as a declared slot being absent,
  and it is how an off-bench device announces its return: slot labels are
  positional, so a reconnected board cannot be predicted onto a label.
- The roster is rejected if an on-bench device declares no slot, or an
  off-bench device declares no `dev_eui` -- the latter would sit in the
  roster looking monitored while nothing about it could be checked.
- Document how a hardware-gate failure reaches an operator: a failed Job
  is the report, and two Prometheus alerts turn it into a push. One
  covers "the run failed", the other "no successful run in 26 hours" --
  the second exists because if the CronJob stops firing there is no
  failed Job to alert on, and absence would otherwise read as health.

### Fixed

- The hardware gate reports an unreadable or empty roster as one line and
  exits 2, instead of raising a traceback. It also rejects a roster with
  no devices: silently checking nothing and exiting 0 is the worst
  outcome for a gate, since it reads as "all clear".

## [0.30.0] — 2026-08-24

### Added

- **Nightly hardware gate (workbench phase 3).** A new
  `wirestudio-hardware-gate` entry point asserts the bench and every
  board on it is still alive: the portal answers, each configured slot
  is present and flashable, its serial recorder captured output
  recently, and ChirpStack saw its DevEUI recently. Exits non-zero on
  any failure. See `docs/workbench.md`; the roster schema is
  `scripts/hardware_gate.example.yaml`.
- Serial liveness and uplink recency are separate checks because they
  fail separately: a board on the reference bench was transmitting
  normally while absent from the USB bus -- alive on the air, but
  unflashable and invisible to any check that only asked ChirpStack.
  Uplink recency is asserted from `last_seen_at`, not from the presence
  of an activation: a device silent since June still had a valid one.
- A missing slot fails rather than resolving. Slot labels are
  positional, so a board that moves ports gets a new label; quietly
  following it would hide exactly the event the gate exists to report.

### Changed

- Workbench phase 3 is scheduled from a cluster CronJob instead of the
  self-hosted runner originally planned. WireStudio is a public
  repository, and a runner on the bench network would let any fork's
  pull request execute code with reach into that network. The tradeoff
  is that the gate cannot annotate a PR.

## [0.29.0] — 2026-08-23

### Added

- **Boot-marker verification (workbench phase 2, server side).** A
  successful flash proves bytes reached the chip and nothing more -- a
  wrong flash size or an undriven front end flashes perfectly and then
  fails at start-up, which is the failure class CI cannot see. The new
  `workbench_verify_boot` MCP tool watches a slot for a line the running
  firmware emits, upgrading "flashed" to "flashed and booted". Supports
  `esphome`, `lorawan` (standalone RadioLib) and `lorawan-esphome`;
  Meshtastic and CircuitPython are explicitly unsupported with the
  reason, rather than approximated.
- Joining is a separate, opt-in check with a 7-minute budget, because
  the first join after a flash reliably fails and only the retry --
  one uplink interval later -- succeeds. Asserting it by default would
  fail on a healthy board.

- **A check that `[Unreleased]` keeps one heading per kind.** Every PR
  adds its own entry, so four PRs each writing `### Fixed` left four
  separate Fixed blocks -- visible only when someone read the whole
  section at release time, which 0.27.0 and 0.28.2 both needed by hand.
  Also catches a misspelled heading (`### Fixes`), which fails the same
  way but looks correct in a diff. Released sections are not checked:
  0.26.0, 0.25.0 and 0.17.0 already carry duplicates, so enforcing
  history would block unrelated work.

## [0.28.2] — 2026-08-23

### Added

- **A gate that keeps `constraints.txt` honest.** The pins added in
  0.28.1 only hold while the file names every package pip installs; add
  a dependency to `pyproject.toml` and it is simply not pinned, nothing
  fails, and builds can drift again. The `constraints` workflow installs
  under the pins on Python 3.11 (the image's) and fails if anything
  arrived unpinned. Runnable locally via
  `scripts/check_constraints.py`.

### Changed

- **Documented that the first join after a flash fails, and that verbose
  logging is not why.** `-1116` (no join-accept) on the boot right after
  new firmware is written is expected: it costs one uplink interval and
  one DevNonce, then recovers. Measured 11 reboots (all joined first
  try) against 4 flashes (all failed first try), on both a default and a
  VERBOSE build -- so the logger level, which the symptom was previously
  attributed to, makes no difference.
- **Board `flash_size_mb` now records where its value came from.** The
  field drives the ESPHome partition table, and the failure is
  asymmetric: under-declaring wastes flash, over-declaring boot-loops
  the board. Six boards now carry provenance -- two verified against
  silicon, three from vendor docs and marked unverified, and
  `esp32-s3-devkitc-1` marked as a floor that must not be raised,
  because Espressif sells it as both an 8MB and a 32MB part under one
  name. `docs/integration_spec.md` explains the asymmetry and how to
  read the real size off an ESP-IDF bootloader.

### Fixed

- **Network failures reported a bare colon and nothing else.** httpx
  raises `ConnectTimeout`, `ReadTimeout`, `PoolTimeout`, `ConnectError`,
  `ReadError` and `RemoteProtocolError` with **no message**, so the
  `f"...: {e}"` used in ~20 places rendered as
  `firmware not available for run <id>: ` or `unreachable: `. Because
  only some failure modes carry text, the same tool gave a useful
  message one minute and an empty one the next -- which read as an
  intermittent bug rather than a whole class of error with nothing to
  say. Exceptions now render through `wirestudio.errors.describe`,
  which falls back to the class name.

## [0.28.1] — 2026-08-22

### Changed

- **Image builds are now constrained.** `pyproject.toml` carries lower
  bounds only and the Dockerfile installed with a bare
  `pip install .`, so two images built weeks apart resolved different
  versions of everything -- including transitive packages nothing
  declares. `constraints.txt` caps the whole set (103 pins, taken from
  the 0.28.0-full image serving prod) and both install lines now use
  `-c constraints.txt`. Refresh procedure in `CONTRIBUTING.md`.

  The prompt was staging and prod landing on different `httpx2` minors,
  a dependency that arrived with mcp 2.x and that no wirestudio code
  imports. They happened to reconverge on the next build, which is the
  actual problem: they agreed by coincidence of timing rather than by
  construction.

## [0.28.0] — 2026-08-22

### Changed

- **Migrated to mcp 2.x**, lifting the `mcp<2` pin carried since 0.24.1.
  2.0 renamed the server package `mcp.server.fastmcp` ->
  `mcp.server.mcpserver` and the class `FastMCP` -> `MCPServer`; the
  decorator, resource and transport API is otherwise unchanged, so the
  39 tools and their registrations move across as-is.

  Three breaks needed real changes rather than a rename:
  `Settings` no longer carries `transport_security` (it is now an
  argument to `streamable_http_app()`, which is where it was always
  used); `call_tool` returns a `CallToolResult` instead of a bare
  content sequence; and the model fields are snake_case
  (`inputSchema` -> `input_schema`, `uriTemplate` -> `uri_template`).

  Note mcp 2.x depends on **httpx2**, a separate distribution from
  httpx. The import names differ, so it coexists with the studio's own
  httpx usage rather than replacing it -- but it is a second HTTP stack
  in the image.

## [0.27.2] — 2026-08-16

### Fixed

- **The LoRaWAN battery example sampled the wrong ADC pin.** The
  `lorawan-battery-uplink` design wired its ADC to `GPIO36` and applied
  no scaling, while both `ttgo-lora32-v1` and `-v2` carry
  `battery_adc: {pin: GPIO35, divider: 2.0}` -- GPIO35 is the pin tagged
  `battery_sense`, and the pack is read through a 1:2 divider. So the
  example sampled an unconnected pin and, even on the right one, would
  have reported half the pack voltage while labelled `V`. Now GPIO35
  with a `multiply: 2.0` filter. The board metadata was already correct;
  nothing consulted it, because the design pinned the connection
  explicitly.

### Changed

- `buildModel` in `WiringView.tsx` builds its bus list with a single-pass
  loop instead of `.map().filter()`, and compares keys with `!==` rather
  than `Array.includes` (#214). No behaviour change.

## [0.27.1] — 2026-08-02

### Changed

- `readConnections` uses a single-pass loop instead of a chained
  `.map().filter()`, and `nextInstanceId` iterates the raw components
  array rather than building throw-away `ComponentInstance` objects to
  read their ids (#209).

### Fixed

- **ESPHome LoRaWAN devices stopped uplinking once the network settled.**
  A 12-byte payload (three float32 fields) joined fine, uplinked once or
  twice, then failed with `RADIOLIB_ERR_PACKET_TOO_LONG` (-4) forever.
  US915 DR0 caps the application payload at 11 bytes and ADR drives the
  rate to DR0 on a strong link, so the failure appeared only after the
  network had settled -- which made it look like a radio or provisioning
  fault. Bumps `lorawan-for-esphome` to a build that re-asserts the
  payload's minimum data rate before every uplink. The standalone
  RadioLib path already did this; the ESPHome external-component path
  never had it.

## [0.27.0] — 2026-08-02

### Added

- **MCP hardware tools — a headless client can now finish a bring-up.**
  The 22 design/library/fab tools stopped at the artifact; putting it on a
  board meant dropping to HTTP. That was the wrong workaround, because
  `/api/mcp` is bearer-gated while `/api/workbench/*` and `/api/lorawan/*`
  carry no auth at all, so "just publish the REST endpoints" meant
  publishing unauthenticated flashing and ChirpStack provisioning.
  Seventeen new tools close it: `workbench_status` / `workbench_slots` /
  `workbench_flash`; `lorawan_chirpstack_status` / `lorawan_compile` /
  `lorawan_provision` / `lorawan_provision_esphome` /
  `lorawan_activation` / `lorawan_workbench_provision`; `fleet_status` /
  `fleet_push` / `fleet_job_status` / `fleet_job_log` /
  `fleet_firmware_info`; and `job_status` / `job_events` / `job_list`.
- **Long operations return a job handle instead of blocking.** Compile,
  flash and workbench-provision stream for minutes, which does not fit a
  tool call that returns once. They now start the work and hand back a
  `job_id` to poll. Fleet builds deliberately keep their own `run_id`:
  that handle belongs to the addon's GitHub run and survives a wirestudio
  restart, so wrapping it in the in-memory registry would only make it
  more fragile.
- Firmware bytes never cross the MCP boundary. `workbench_flash` takes a
  `fleet_run_id` and fetches the artifact server-side; `fleet_firmware_info`
  reports size and availability rather than returning megabytes of base64
  into a context window.

### Fixed

- **`workbench_flash` picks its offset by inspecting the artifact.** A
  merged image (bootloader + partition table + app) goes to `0x0`; a bare
  app image goes to `0x10000`. The kind is detected from the bytes -- an
  ESP-IDF partition table at `0x8000` -- because the endpoint that serves
  them does not reliably say which is which.

  This landed the hard way. `fleet/client.py` documented `/firmware` as
  the app image and `/firmware/factory` as the merged one, so an earlier
  attempt at this fix wrote `/firmware` to the app offset. Against the
  live addon `/firmware` is in fact a *merged* image and
  `/firmware/factory` 404s, so that put a bootloader in the app partition
  and boot-looped a Heltec V4 (`No bootable app partitions in the
  partition table`). Recovered by rewriting the same artifact at `0x0`.
  The client docstring now records what the addon actually serves.

- **The `recommend` MCP tool was dead — it ran `library_detail` instead.**
  Two `@mcp.tool` decorators were stacked on one function. FastMCP's
  decorator returns `fn` unchanged, so both names bound to
  `library_detail`, and the real `recommend` body was never registered.
  MCP clients calling `recommend(query=...)` got a pydantic
  `ValidationError` for `library_detailArguments`. The existing test
  asserted the set of tool *names*, which was correct either way — the
  suite now also asserts no two tools share a function, and that
  `recommend` takes `query` and returns results.

## [0.26.3] — 2026-08-01

### Fixed

- **A design could be pushed to fleet once and never updated.** The addon
  keys its target list by `target`; the client read only `filename`/`name`,
  so the existence check was always empty, every push took the create
  branch, and re-pushing an existing device failed with
  `create_target failed: ... already exists` instead of overwriting.
  The test fake returned the assumed shape rather than the addon's, which
  is why nothing caught it -- the fake now mirrors a live response.

## [0.26.2] — 2026-08-01

### Fixed

- **ESPHome configs declared 4 MB regardless of the board.** ESPHome
  defaults to 4 MB, so a 16 MB board silently got a 4 MB partition table --
  three quarters of the flash unused and OTA slots smaller than the chip
  allows. Nothing errors, which is why it went unnoticed; found reading
  `SPI Flash Size : 4MB` out of a Heltec V4 whose chip reports 16 MB by
  JEDEC ID. The `esp32:` block now carries `flash_size` from the board
  file, matching what the standalone path already pins via
  `board_build.flash_size`.

  This makes `flash_size_mb` load-bearing for every ESP32 design. Only
  five boards claim more than 4 MB, and over-declaring is the direction
  that boot-loops (see the V2 fix in 0.25.0) -- of those, only
  `heltec-wifi-lora32-v4` is verified against real silicon here. ESP8266
  boards are unaffected; the key is emitted inside the `esp32:` branch.

## [0.26.1] — 2026-08-01

### Fixed

- **Fleet firmware artifacts were unfetchable by run_id.** The addon keys
  artifacts by `job_id`, while the push response, the status poll and the
  studio's own route are all keyed by `run_id`. Passing the run_id
  straight through 404s as "firmware artifact not available", which reads
  as *the build produced nothing* rather than *wrong key* -- so a compile
  that had actually succeeded looked broken, and the documented
  provision -> compile -> flash flow could not complete. `get_firmware`
  now resolves the run to its jobs and retries; a job_id still works
  directly. Found fetching a real fleet build for a Heltec V4.
- **Stale docstrings claimed the fleet artifact endpoint did not exist.**
  It does, and the comment cost real debugging time.

## [0.26.0] — 2026-08-01

### Fixed

- **Bumped the lorawan-for-esphome pin to the SX1262 radio-keys merge.**
  Its `RADIO_SCHEMA` is strict, so the ref and the emitted keys move
  together: an older ref rejects `tcxo_voltage`, `dio2_as_rf_switch` and
  `setup_high` outright rather than ignoring them.
- **ESPHome LoRaWAN path was unusable on SX1262 boards with a PA.** The
  rendered radio block dropped the board's `setup_high` front-end pins, so
  a Heltec V3/V4 came up deaf -- `begin()` returns OK, uplinks report as
  sent, and nothing reaches the gateway. They are now emitted alongside
  `tcxo_voltage` and `dio2_as_rf_switch`, which needs
  lorawan-for-esphome#8 to accept them.
- **GNSS stayed unpowered on boards that gate it.** A board carrying a
  GNSS power-enable (Heltec V4: `GPS_EN` on GPIO34, active low) rendered
  no way to assert it, so the module sat dark and the UART never produced
  a sentence -- indistinguishable from "no satellite fix". `uart_gps` now
  emits a GPIO switch with `restore_mode: ALWAYS_ON` when the component
  carries an enable pin, matching what the standalone firmware does in
  `setup()`.

### Fixed

- **LoRaWAN builds still failed in the deployed image.** The 0.25.0 fix
  moved `PLATFORMIO_CORE_DIR` to the writable volume but pointed
  `PLATFORMIO_PLATFORMS_DIR` / `PACKAGES_DIR` straight at the prewarmed
  tree baked into the image. PlatformIO takes its lock at `<dir>.lock` --
  a *sibling* of the managed directory, not a child -- so every build died
  with `OSError: [Errno 30] Read-only file system:
  '/opt/pio/platforms.lock'`. The core dir now holds symlinks to the
  prewarmed trees (created by a new entrypoint, since /data is a volume
  and masks anything written at build time), so locks land on the writable
  volume while the content still resolves to the read-only baked copy --
  no re-download, nothing duplicated onto the volume.
- **`platformio_status()` reported available for that install.** The probe
  checked core-dir writability and platform-tree readability, which is
  exactly what this failure slips past. It now also verifies the lock path
  beside each managed directory is writable. Found by running a real build
  against the deployed image: status said available, the build failed.

### Added

- **Feedback link in the header.** An icon beside the theme and settings
  buttons opens the repo's new-issue form, prefilled with the running
  version, the current board, and the browser UA -- the details a bug
  report otherwise costs a round trip to collect. A plain link rather
  than an API call: no token, nothing leaves the browser, and GitHub
  shows the reporter the whole body before they submit. The design is
  deliberately not included.

### Changed

- **Regenerated the library coverage matrix.** It still reported 64
  components; `battery_adc` had been added without refreshing the
  generated doc.

## [0.25.1] — 2026-07-30

### Changed

- **`WORKBENCH_TOKEN` is optional.** Phase 1 required it, reasoning that
  every comparable gate pairs a host with a credential. That was wrong:
  those tokens authenticate to services that check them, and the stock
  workbench portal checks nothing. Requiring it gated nothing -- anyone
  able to set the URL can set a token too -- while implying a credential
  that does not exist and pushing operators to seal a dummy value into a
  secret store. `WORKBENCH_URL` alone now configures the integration, and
  the token is sent only when set, for a bench fronted by something that
  does authenticate.

## [0.25.0] — 2026-07-30

### Added

- **Workbench remote flash transport (phase 1, server side).** New
  `wirestudio.workbench` client and `/workbench/*` routes behind a
  `WORKBENCH_URL` + `WORKBENCH_TOKEN` gate: `GET /workbench/status`
  (always 200, carries `available`/`reason`/`configure_hint` like the
  fleet and enclosure gates), `GET /workbench/slots`, and
  `POST /workbench/flash` streaming the bench's esptool output as SSE.
  The studio uploads the image and the Pi flashes its own USB rather
  than the studio driving esptool over RFC2217 -- esptool's block
  protocol is round-trip bound, so one bulk transfer survives the very
  link that makes remote flashing necessary, and the bench keeps owning
  the bench. RFC2217 remains what phase 2 relays for serial.
- **Hardware-validated against the reference bench.** The wire format is
  verified, not assumed: parts are keyed `bin@<offset>`, and the portal
  answers once with `{ok, output, returncode}` rather than streaming, so
  the client parses that log into per-line SSE events and treats a
  non-zero `returncode` as a failure instead of reporting a successful
  flash. Progress therefore arrives at completion, not live; liveness
  needs the phase-2 serial relay.
- **Slot pre-flight.** A flash is refused before the stream opens (409)
  when the slot is busy, flapping, or holds no serial device, so a
  wedged bench reports as a bench fault rather than a firmware failure.
  A token is required alongside the URL: the studio pushes firmware at
  an operator-supplied host, so a URL-only gate would let any
  deployment flash any reachable bench.

### Added

- **Headless LoRaWAN bring-up on a bench slot.**
  `POST /lorawan/workbench/provision` flashes, registers, provisions and
  verifies a board in one call, streaming a phase per step. Registration
  already existed and was designed around a host that supplies the eFuse
  MAC and types the keys into the device's serial prompt; that host could
  only be the browser. `wirestudio.workbench.serial.answer_prompts` drives
  the same dialogue over the slot's RFC2217 port, so the flow no longer
  needs anyone at the bench. Phase order is forced by the hardware: the
  flash runs first because esptool's own output is the only place the MAC
  appears (the bench exposes no chip-detect), and the erase must precede
  registration so `provision_device`'s DevNonce flush lands after the
  device's counter restarts. Keys are redacted from the log
  case-insensitively -- devices echo them back, in uppercase.

### Fixed

- **A tenant-scoped ChirpStack API key was reported as unusable.**
  `ping()` and `default_tenant_id()` both probed `TenantService.List`,
  which is admin-only, so the least-privilege key the ChirpStack UI hands
  out made `/lorawan/chirpstack/status` report the server as down and
  every provisioning chain fail with a bare `UNAUTHENTICATED`. Set
  `CHIRPSTACK_TENANT_ID` and the client skips the admin-only lookup and
  probes with a tenant-scoped call instead; the error now says so rather
  than reading as a bad token.
- **LoRaWAN builds could not run in the deployed image.** Three faults
  stacked. (1) The `-full` image builds on `kicad/kicad:8.0`, which
  already occupies uid 1000, so its bare `useradd appuser` landed on
  1001 while manifests pin `runAsUser: 1000`. (2) PlatformIO creates
  platform directories `0700`, so the prewarmed toolchain was unreadable
  to any other uid -- `PermissionError` on a plain `listdir`. (3)
  `PLATFORMIO_CORE_DIR` was baked to `/opt/pio`, but PlatformIO writes
  `appstate.json` and lockfiles there on every invocation, which cannot
  work under `readOnlyRootFilesystem: true`. The core dir now defaults to
  `/data/pio` with the prewarmed toolchain kept read-only via
  `PLATFORMIO_PLATFORMS_DIR` / `PLATFORMIO_PACKAGES_DIR`, the cache under
  `/tmp`, and the baked tree is `chmod a+rX` so any runtime uid can read
  it. No re-download, and uid no longer has to match.
- **`platformio_status()` reported available for a toolchain that could
  not build.** It only ran `pio --version`, which never touches the core
  dir, so the UI offered the LoRaWAN flow and the failure surfaced as a
  mid-build traceback. It now verifies the core dir is writable and the
  platform tree readable, and reports the specific reason.
- **Uplinks silently stopped at DR0 (`PACKET_TOO_LONG`).** The datarate
  was set once after join, so a restored session or an ADR downlink could
  drop the device to DR0, whose US915 payload cap is 11 bytes. Every
  `sendReceive` then failed `RADIOLIB_ERR_PACKET_TOO_LONG` (-4) while the
  device stayed joined and looked healthy -- the only evidence was a
  serial line nobody reads. Hardware-confirmed on a T-Beam: a 22-byte
  payload failed -4 indefinitely, and re-asserting the rate per uplink
  fixed it (`fCnt` advancing at DR1, decoded object correct).
- **Generated codec fabricated zeros for a short payload.** `decodeUplink`
  read its full field layout unconditionally, so an uplink shorter than
  the layout read past the end -- JS yields `undefined`, the shifts coerce
  it to 0, and the codec returned a complete set of plausible zeros with
  `errors: []`. Home Assistant showed those as real readings. The codec
  now length-checks first and reports the mismatch as a decode error.
  Observed live: a device sending one `0x00` byte decoded as nine
  zero-valued sensor fields.
- **DHT pin rendered as literal `None` in LoRaWAN firmware.** A DHT
  requested through `lorawan.dht22` has no wiring, so `firmware_gen`
  sets the render context's `pin` to `None`; Jinja's `default()` only
  substitutes for *undefined* values, so the chain never fell through
  to `params.pin` and emitted `DHT dht(None, DHT22);` -- C++ that does
  not compile. The template now tests for none explicitly (and avoids
  `or`, which would discard a legitimate GPIO0). Regression tests cover
  the synthesized-DHT path and the T-Beam's AXP192 rail init, neither
  of which was exercised before.

### Changed

- **Roadmap: Workbench featureset.** docs/index.md gains a planned
  integration with the SensorsIot Universal Embedded Workbench as the
  studio's hardware truth layer -- remote flash transport over RFC2217,
  boot-marker verification, a nightly hardware gate, and a functional
  loop with SDR TX checks -- phased and env-gated like every other
  integration. docs/workbench.md carries the full capability map and
  design constraints.
- **Roadmap accuracy pass.** Four claims in docs/index.md contradicted
  the repo and are corrected: coverage is "zero unexplained gaps", not
  "zero uncovered" (`axp192` is a permanent baseline entry, so the
  matrix reads 63/64); the `.kicad_sch` render in CI moves from Next to
  shipped (the `kicad-render` gate already runs it); PCB layout is
  "Verified (routed)" now that the `pcb-route` gate holds examples to
  the routed bar; CircuitPython flashing is tagged 0.24 rather than
  unreleased. The outstanding mcp 2.x migration behind the 0.24.1
  `mcp<2` pin is recorded as Known debt.
- **Workbench: constraints and phase rationale.** Phase 1 is motivated
  by reach rather than convenience -- a LoRaWAN board can only be
  join-tested where a gateway is in range, so a bench remote from the
  developer has no WebSerial path at all. Four design constraints
  folded in: `WORKBENCH_URL` alone is not authorization (host allowlist
  + token ship with the transport, since the workbench API is
  unauthenticated and the server-side fetch is an SSRF primitive);
  bench resources are exclusive and callers must expect a busy state;
  hardware faults report distinctly from test failures behind a
  pre-flight self-test; RF checks assert against a fixed-gain baseline
  rather than energy presence. The phase-3 self-hosted runner is stated
  as a prerequisite cost.

## [0.24.1] — 2026-07-29

### Fixed

- **Pin `mcp<2`.** mcp 2.0.0 (released 2026-07-28) removed the
  `mcp.server.fastmcp` import path, so images built after it crashed at
  boot with ModuleNotFoundError -- the 0.24.0-full image never came up
  (prod stayed on 0.23.0). Migrating to the mcp 2.x API is follow-up
  work; the pin restores a bootable image.

## [0.24.0] — 2026-07-29

### Added

- **CircuitPython flashing.** The unified flash dialog gains a CircuitPython
  framework: `GET /circuitpython/firmware?board=` proxies the official
  release image from downloads.circuitpython.org (combined binary, flashed
  at 0x0 with full erase over the same WebSerial/esptool-js mechanism),
  resolving the newest stable version from the adafruit/circuitpython
  releases API. All 22 ESP32/S3/C3/C6 boards map to a verified build --
  exact where upstream has one (Heltec V3, M5Stack Atom family, XIAO,
  SuperMinis, devkits), a pin-compatible generic image otherwise (flagged
  in the status response and warned about in the UI). ESP8266 boards are
  unsupported (CircuitPython dropped the port).
- **Starter code.py.** `GET /circuitpython/code?board=` generates a
  dependency-free starter from the board's library metadata -- Vext
  power-up, onboard-LED blink, default-I2C scan, and a boot-time pin
  listing. The flash dialog shows it post-flash with save-to-CIRCUITPY
  (File System Access API) and download buttons.
- **Heltec WiFi LoRa 32 V4 GNSS auto-wiring.** The board's SH1.25-8 GNSS
  connector is now an onboard peripheral (`gps_gnss`), so seeding the board
  auto-places a GPS wired to the correct UART pins (MCU rx GPIO38, tx GPIO39
  -- matching Meshtastic's `heltec_v4` `GPS_TX_PIN`/`GPS_RX_PIN`). The
  onboard-GPS seed handler now matches any `gps_*` peripheral key, not just
  `gps_neo6m`. The seed also carries a board's GNSS power-enable pin (V4:
  GPS_EN on GPIO34, active low), and the `uart_gps` LoRaWAN setup fragment
  drives it so the module powers up instead of staying dark.

### Changed

- **Documentation sweep.** README / docs index / user guide / library
  reference / integrations / deployment / web README brought current:
  the five-framework flash dialog, firmware-proxy endpoints, module map
  (seed, intent, inventory, jlcpcb), the boards and components added
  since 0.19 (SuperMinis, XIAO C3, TTGO LoRa32 V2.1, steppers/fans/
  potentiometer/Grove AHT20/AXP192), version examples bumped to 0.23.0,
  and stale claims removed (web UI persistence, test counts, shipped
  PCB milestones still listed as future).
- **GPS/GNSS component discoverability.** `uart_gps` gains `gnss`, `gps`,
  `uc6580`, and `ublox` aliases (and a `gnss` use-case) so an inspector
  search for "GNSS" finds it. Covers the Heltec V4's UC6580-class module.

## [0.23.0] — 2026-07-26

### Added

- **Unified flash dialog.** The Radio toolbar button now opens a single
  flashing surface with a framework picker -- ESPHome, Tasmota, LoRaWAN,
  Meshtastic -- all sharing the one WebSerial/esptool-js mechanism. ESPHome hands off to the fleet push dialog; LoRaWAN keeps
  its compile-flash-provision flow; Tasmota fetches the official release
  image through the server proxy, flashes with full-chip erase, then
  offers a post-flash serial config push: the design's template plus
  optional WiFi credentials sent as `Backlog0` console commands.
  Credentials stay client-side -- never sent to the server or stored in
  the design.
- **Tasmota firmware proxy.** `GET /tasmota/firmware?chip=` streams the
  matching official release image from ota.tasmota.com with the flash
  offset in `X-Flash-Offset`; `GET /tasmota/firmware/status` gates the
  UI on upstream reachability.
- **Meshtastic flashing.** `GET /meshtastic/firmware?board=` proxies the
  official release factory image from meshtastic.github.io for the radio
  boards (Heltec V2/V3/V4, T-Beam, TTGO LoRa32), resolving the newest
  stable version from the same release-list API the official web flasher
  uses. Flashed at 0x0 with full erase via the unified dialog. Not a
  target plugin -- devices run stock firmware, so nothing is generated
  from the design. Region/channel config is protobuf over serial; the
  dialog links to client.meshtastic.org, and an in-studio config push
  via `@meshtastic/js` moves to the backlog.

## [0.22.0] — 2026-07-26

### Added

- **Pin notes on every GPIO dropdown.** The safe / in use / caveat
  annotations from the bus pin selectors now also appear in the
  connection editor's GPIO pin dropdowns, sharing the same
  pinCaveat/readUsedPins logic.

- **Tasmota target.** Third generation target alongside esphome and
  lorawan: emits a Tasmota device template from a solved design --
  `POST /tasmota/template`, `python -m wirestudio.targets.tasmota`, and
  the target seam. GPIO function ids and per-chip template layouts are
  sourced from Tasmota's `tasmota_template.h`; 15 library components
  gain `tasmota:` mappings (relays, switches, DHT/DS18B20, WS2812, ADC,
  HC-SR04, rotary, counter, buzzer, IR, HX711, CSE7766, HLW8012), and
  I2C sensors ride the bus pins via Tasmota autodetection. The
  smart-plug example reproduces the Sonoff S31 template convention.
  Meshtastic and CircuitPython targets are added to the roadmap backlog.

## [0.21.3] — 2026-07-25

### Changed

- **Cleaner schematic renders.** Power/rail nets are marked as stubs
  (short labeled stubs at each pin instead of routed wires), and
  generate_schematic runs with auto_stub (high-fanout nets become
  labeled stubs; routing failures fall back to a stubbed drawing) and
  rotate_parts. Cuts most of the label/wire overlap in the preview.

## [0.21.2] — 2026-07-25

### Added

- **kicad-render CI gate.** New workflow runs the full schematic render
  pipeline (SKiDL -> .kicad_sch -> `kicad-cli sch export svg`) on real
  KiCad 8 for solved and unsolved example designs -- the pipeline the
  netlist-level gate never exercised.

### Fixed

- **Schematic render: KiCad 8 rejected SKiDL's output.** skidl 2.2.x's
  kicad8 writer emits two KiCad 9 constructs -- the nested
  `(pin_numbers (hide yes))` form and the `embedded_fonts` token --
  that KiCad 8's parser rejects with a swallowed exception, presenting
  as "Failed to load schematic file". The generated script rewrites the
  emitted `.kicad_sch` to KiCad 8 grammar. Diagnosed and now guarded by
  the kicad-render gate.

- Render errors now include kicad-cli stdout, where its parse detail
  lands; stderr alone carried only "Failed to load schematic file".

## [0.21.1] — 2026-07-25

### Fixed

- **Schematic render failed on designs with unassigned pins.** Unbound
  connection targets (empty gpio pin / bus id) emitted stub
  `GPIO_UNBOUND` nets that SKiDL's schematic router cannot route on
  larger designs (`GlobalRoutingFailure`). Unassigned pins now stay
  unconnected in the generated script (annotated `run Solve Pins`), and
  `generate_schematic(allow_routing_failure=True)` degrades any other
  routing failure to a stubbed-net render instead of a 500.

## [0.21.0] — 2026-07-25

### Added

- **Heltec WiFi LoRa 32 V4.** Board library entry (ESP32-S3R2, SX1262
  behind a GC1109/KCT8103L RF front end, 16MB flash, SSD1315 OLED, GNSS
  and solar connectors), pinout from the Meshtastic heltec_v4 variant.
  New `radio.setup_high` board field: pins the generated LoRaWAN
  firmware drives HIGH before `radio.begin()` -- the V4's FEM
  power/enable/mode pins, without which the radio is deaf. Rides the V3
  PlatformIO board def until upstream ships a V4 one.

### Fixed

- **API errors show the server's detail.** The web client now surfaces
  the response's `detail` string (tool stderr, validation text) instead
  of a generic `POST /path -> 500`, so schematic/PCB render failures are
  diagnosable from the UI.

- **UART buses auto-select pins (#171).** Adding a bus without board
  defaults now lands on auto-selected free pins: prefers pins whose
  capability tags match the slot (non-console uart_tx/uart_rx), skips
  pins already used by buses or connections and pins with caveats
  (strap, console UART, USB, input-only, fixed onboard roles). Bus pin
  dropdowns annotate every option -- safe, in use, or the specific
  caveat -- so manual picks stop landing on warning-prone pins.

- **Inspector add-component UX.** The add-component picker stacks
  vertically (full-width dropdown, Add button below) instead of forcing
  a horizontal scroll that pushed the button out of view, and the
  library-component inspector gains an "Add to design" button so parts
  picked from the left sidebar can be added directly.

## [0.20.1] — 2026-07-25

### Fixed

- **Schematic render 500 in deployments.** The generated SKiDL script now
  pins `skidl.set_default_tool(KICAD8)` and sets the symbol search path
  from the `KICAD*_SYMBOL_DIR` env vars itself. Previously only the CI
  runner did this, so running the script raw -- which is exactly what
  `/design/kicad/render` and the download-and-run flow do -- left SKiDL
  on its legacy default tool and failed with `Can't open file: RF_Module`.
  Verified end-to-end: raw script -> .kicad_sch on skidl 2.2.3 against
  pinned kicad-symbols 8.0.0.

## [0.20.0] — 2026-07-25

### Added

- **Seeed XIAO ESP32C3 + Grove AHT20 (spec tier).** First library entries
  added through the manufacturer-outreach spec flow: pre-filled from
  Seeed's published docs per `docs/integration_spec.md`, marked
  unverified with VENDOR REVIEW items flagged in-file, exercised by the
  new `xiao-grove-climate` example.

- **Submission template.** `docs/submission.template.yaml` is a copyable,
  commented starting point for the vendor manifest the integration spec
  describes.

- **Vendor integration spec.** `docs/integration_spec.md` documents what a
  manufacturer supplies to list a board or component in the library: the
  exact component/board YAML schemas annotated by consuming phase (catalog,
  pin solving, electrical validation, ESPHome generation, schematic/PCB,
  enclosure, LoRaWAN), a submission-bundle manifest for commerce metadata,
  and the spec/reviewed/validated listing tiers.

- **Wiring view.** New default tab in the design pane: a read-only SVG
  net graph built directly from `design.json` -- board rails/GPIOs on
  the left, buses in a middle lane, components on the right, edges
  colored by net class with hover highlighting of the whole net.
  Unassigned pins surface in red. Live under render errors (same as the
  JSON tab); no new dependencies.

- **`[pcb]` extra.** `pip install wirestudio[pcb]` now pulls the
  pip-installable half of the KiCad pipeline (skidl + cairosvg), and
  `Dockerfile.pcb` installs it, fixing the schematic preview being
  unavailable in the -pcb/-full images (skidl was never installed).
  kicad-cli and the footprint/symbol libraries remain native installs.

- **Schematic and PCB tabs.** Advanced mode adds two design-pane tabs
  that render server-side previews on demand: the existing schematic
  pipeline (SKiDL + kicad-cli), and a new placed-board preview via
  `POST /design/kicad/pcb/render` (`kicad-cli pcb export svg`, cropped
  to the board area) with a `/status` probe. Both gate on server tool
  availability and surface the missing-tool reason inline.

- **Light theme.** The web UI now ships light and dark themes: a header
  toggle persists the choice to localStorage, first visit follows the
  system `prefers-color-scheme`, and a pre-paint snippet in `index.html`
  avoids the wrong-theme flash. Implemented entirely as token overrides
  on `data-theme="light"` -- components are theme-agnostic. Dialogs
  opened via the shared primitive now also close on Escape.

### Changed

- Single-pass collection building in ConnectionForm and Inspector (#155).

- **Web UI design system.** Token-based theme in `index.css` (Tailwind
  `@theme`): copper accent, layered surface scale, ink text scale, violet
  reserved for agent surfaces, semantic emerald/amber/rose kept for
  success/warn/error. Self-hosted Inter Variable + JetBrains Mono. New
  `ui.tsx` Dialog/Button/Input/FieldLabel primitives replace the
  hand-rolled overlay scaffolding in most dialogs; every component moved
  off ad-hoc zinc/blue classes. Visual only — no behavior changes.

## [0.19.1] — 2026-07-18

### Added

- **`-full` image variant: PCB toolchain + LoRaWAN worker in one image.**
  `Dockerfile.pcb` gains the same `WITH_LORAWAN` build-arg as the default
  Dockerfile (PlatformIO + the `[lorawan]` extra + espressif32 prewarm,
  installed into the app venv); a new `full-image` CI job publishes it as
  the `-full` tag suffix. This is the every-feature image prod runs —
  autoroute/fab AND LoRaWAN compile/flash from one deployment — replacing
  `-lorawan` as the prod-tracked variant.

## [0.19.0] — 2026-07-17

### Added

- **Autoroute surfaces: HTTP, MCP/agent, web UI, and a `-pcb` image.**
  `POST /design/kicad/route` streams the Freerouting log as SSE and the
  routed board downloads from `GET /design/kicad/route/{cache_key}`;
  `GET /design/kicad/route/status` gates the feature. The fab Gerber/package
  endpoints accept `?route=true` (503 toolchain missing, 409 routing failed),
  and `fab_status` reports `route`/`route_reason`. New `route_pcb` MCP/agent
  tool returns a routed summary (segments, vias, cache_key). The KiCad export
  dialog gains an **Autoroute** section (route button, live log, routed-board
  download) and a **Routed** checkbox on the fab package. A new
  `Dockerfile.pcb` variant (published as the `-pcb` tag suffix) bakes in
  KiCad 8 + pcbnew, the pinned libraries, a Temurin JRE, and the pinned
  Freerouting jar so a deployment can route out of the box; route results
  cache under `/data/route-cache`.

- **PCB autorouting (Freerouting).** `wirestudio/kicad/route.py` routes a
  generated `.kicad_pcb`: Specctra DSN export via pcbnew (a dependency-free
  `pcbnew_bridge.py` run under the system python — kicad-cli has no Specctra
  support, and KiCad >= 8 is required for the headless SES import),
  `freerouting.jar` in batch mode (`-mt 1`; multithreaded routing is a known
  source of KiCad-DRC clearance violations), then SES import back into the
  board. Subprocess-based throughout, watchdog-killed on stagnation, results
  content-addressed like the firmware cache. Gated by `route_status()`
  (pcbnew bridge + java + `WIRESTUDIO_FREEROUTING_JAR`); CLI at
  `python -m wirestudio.kicad.route`. A new `pcb-route` CI gate routes
  representative examples and holds them to the routed bar: copper present,
  zero unconnected items, no non-waived error-severity DRC violations —
  verified end-to-end against KiCad 8 + Freerouting 2.2.4 (four boards
  route clean). HTTP/MCP/web-UI surfaces and a toolchain image are the
  follow-up; this lands the pipeline and its gate.

### Documentation

- **Deployment docs reconciled with the actual GitOps flow.** `docs/deployment.md`
  and the `deploy/` reference manifests no longer describe the removed
  `bump-dev`/`bump-prod` CI jobs or a `dev` branch (the project is trunk-based).
  They now present the argocd-image-updater flow the upstream cluster runs
  (staging tracks `:main-lorawan` by digest; prod follows the newest
  `:X.Y.Z-lorawan` release tag), plus the manual `newTag` option. Also fixed a
  broken image tag in `deploy/k8s.yaml` (`:v0.17.1`, which never existed in the
  registry) — now `:0.18.0`.
- **Docs roadmap: PCB layout marked Verified (unrouted).** `docs/index.md`
  Priority 4 no longer claims the layout is "not yet in flight" — it now
  records the shipped `.kicad_pcb` emit (0.14.0) and fab outputs (0.15.0)
  with their CI gates, leaving Freerouting autorouting as the open step.
- **README leads with the hardware design angle.** The intro now frames the
  studio around what stock ESPHome's Device Builder doesn't do — electrical
  metadata, CSP pin solving, electrical validation, and the physical artifacts
  (wiring, schematic, PCB, fab bundle, enclosure) — instead of board/component
  selection. Also reconciled the status table with reality: KiCad PCB layout
  (0.14.0) and fab outputs (0.15.0) move from Deferred to Verified with their
  CI gates linked, only Freerouting autorouting stays deferred; version
  references and the Docker quickstart tag move to `0.18.0` (the `v0.17.1`
  tag never existed in the registry).

## [0.18.0] — 2026-07-11

### Added

- **Strict mode.** A design-level `strict: true` toggle flips the permissive
  default: instead of surfacing electrical/CSP violations as non-blocking
  warnings, any warn/error compatibility entry or design warning now blocks
  generation. Enforced uniformly across the render + validate MCP/agent tools,
  the `/design/render` and `/fleet/push` HTTP endpoints (design field or
  `?strict=true` override), and the `wirestudio.generate` CLI (`--strict`).
  The shared `strict_blockers()` helper is the single source of truth for what
  blocks. Living on the design keeps generation a pure function of design.json.
  Set it via the new `set_strict` MCP/agent tool or the Web UI's STRICT toggle
  (which now persists into `design.strict` instead of a transient request flag).
- **Potentiometer and 12V PWM fan components.** `potentiometer` models a
  three-terminal analog knob (VCC / wiper / GND) read via the ADC; `pwm_fan`
  models a 4-wire 12V fan, emitting the 25kHz PWM output, the `speed` fan
  entity, and the tachometer `pulse_counter` in one part. The PWM platform
  auto-selects `ledc` on ESP32 and `esp8266_pwm` on ESP8266. New
  `solder-fan` example wires the two together on a Wemos D1 Mini.
- **Module library batch.** Four composite modules that drop in pre-wired:
  `fan-controller` (pwm_fan + potentiometer + status LED -- the solder-fan
  as one selection), `relay-4ch` (four gpio switch outputs), `motion-light`
  (HC-SR501 PIR + addressable LED), and `env-display` (BME280 + OLED sharing
  one I2C bus). Brings the module count from 1 to 5.

### Fixed

- **Pin solver respects PWM and interrupt pin limits.** New `requires_pwm` /
  `requires_interrupt` flags on library pins let the solver hard-exclude pins
  that can't do the job -- e.g. ESP8266 GPIO16 (D0), which has neither timer
  PWM nor edge interrupts -- and prefer `pwm`-tagged pins for PWM outputs.
  Applied to `pwm_fan` (PWM/tach), `rtttl` (PWM), and `pulse_counter` (tach);
  previously a PWM output or pulse counter could be auto-assigned to D0 and
  silently fail on hardware.
- **Validator catches PWM/interrupt pins bound by hand.** The compatibility
  checker now emits a `function_unsupported` error when a `requires_pwm`
  output or `requires_interrupt` input is wired to a `no_pwm` / `no_interrupt`
  board pin, closing the gap for locked or hand-edited designs the solver
  never touches.

## [0.17.3] — 2026-06-28

### Fixed

- **Component inventory now persists across redeploys.** `INVENTORY_PATH` was
  never set, so `inventory.json` fell back to a package-relative path on the
  container's ephemeral root filesystem and was lost on every pod restart. The
  Dockerfile now sets `INVENTORY_PATH=/data/inventory.json`, putting it on the
  `wirestudio-data` PVC alongside designs and sessions.

### Documentation

- **MCP token UI documented.** The MCP guide's "Copy the token" step and the
  user guide's Web UI section now point at the header **Settings** (gear)
  dialog for viewing, copying, and regenerating the MCP bearer token.

### Added

- **MCP bearer token: view and rotate from the web UI.** The token was only
  discoverable by reading `~/.config/wirestudio/mcp-token` or grepping server
  logs. A Settings dialog (header gear icon) now shows it masked with a reveal
  toggle, a copy button, and a regenerate action. Two routes back it on the
  unauthenticated API surface (a client must see the token before it can
  present it): `GET /mcp/token` -> `{ token, managed }` and `POST
  /mcp/token/rotate`. Rotation takes effect without a restart -- the bearer
  middleware now reads the live token from a `TokenStore` on each request
  instead of capturing it at mount time; `resolve_token()` stays as a thin
  delegate. When the token is set via `WIRESTUDIO_MCP_TOKEN` it is shown
  read-only and rotation returns 409 (the operator owns the secret).

- **LoRaWAN: flash fleet-built firmware via WebSerial from the provision
  dialog.** Closes the workflow gap where the external-component LoRaWAN
  path built firmware on the fleet but had no way to land it on a headless
  device (no network OTA, no fleet flasher). New
  `FleetClient.get_firmware(run_id, *, factory=)` + `GET
  /fleet/jobs/{run_id}/firmware[?factory=true]` route ferry the addon's
  build artifact through the studio (browser never holds `FLEET_TOKEN`),
  mirroring the standalone path's `/lorawan/firmware/{cache_key}` so the
  existing `lib/flash.ts` consumes both paths identically. The provision
  dialog gains a **Flash via WebSerial →** step after a successful Push to
  fleet: polls the run-status endpoint until the verdict is `passed`,
  pulls the factory image, then writes it to a blank board at 0x0 with
  `eraseAll: true` (NVS is empty, `/lorawan/provision-esphome` re-flushed
  DevNonces, so the wipe is safe per §2.1). Scoped in
  `docs/lorawan/fleet-firmware-flash.md`. The upstream addon endpoint is
  still being implemented; until it ships, the button stays available but
  the call resolves to 404 with a clear "firmware artifact not available"
  message rather than a silent hang.

## [0.17.2] — 2026-06-20

### Fixed

- **LoRaWAN external-component path now renders headless.** The renderer
  emitted `wifi:` / `api:` / network `ota:` / `captive_portal:` whenever
  the design carried a `fleet.secrets_ref`, including on
  `lorawan-for-esphome` designs. Per the upstream README, all four
  blocks reboot-loop the device when the network is unreachable
  (`wifi:` and `api:` default to `reboot_timeout: 15min`), and every
  reboot burns a DevNonce in the OTAA flow -- the device eventually
  stops joining. The fleet/HA addon path's headless field nodes need
  *no* network stack. The renderer now drops the four blocks (including
  any set via `esphome_extras`) whenever `design.lorawan.payload` is
  non-empty. The `lorawan-battery-uplink` golden was regenerated to
  match. User-reported during a Push-to-fleet flow that produced YAML
  the fleet wouldn't compile cleanly.
- **LoRaWAN: render passes SCK / MISO / MOSI to lorawan-for-esphome.**
  v0 of the upstream component constructed RadioLib's `Module` without
  calling `SPI.begin(sck, miso, mosi, cs)`, so it used arduino-esp32's
  VSPI defaults (18/19/23/5). TTGO LoRa32 v1 (and most LoRa boards)
  wire the radio to non-VSPI pins (5/19/27/18) -- the SX1276
  chip-version readback returned garbage and the join failed with
  `ERR_CHIP_NOT_FOUND (-2)`. Renderer now emits `sck_pin` / `miso_pin`
  / `mosi_pin` in the radio block, sourced from the board library's
  `default_buses.spi`. Pinned to `lorawan-for-esphome` @
  `1f7ee9a` (lorawan-for-esphome#2) which adds the matching schema
  fields and calls `SPI.begin()` before constructing the RadioLib
  Module. Also moves `_LORAWAN_FOR_ESPHOME_REF` off `main` to that
  pinned SHA, closing the `# TODO: pin to a commit SHA` left from the
  W2 spike. User-reported during the first hardware join attempt on a
  freshly flashed TTGO LoRa32 v1.
- **LoRaWAN: `create_device` is actually idempotent now.** ChirpStack v4
  scopes `dev_eui` uniquely per tenant (not per application) and leaks
  the SQLite UNIQUE constraint as `INTERNAL` rather than `ALREADY_EXISTS`
  on a duplicate. `create_device` now resolves the conflict via a
  follow-up `Device.Get`: same application -> the documented idempotent
  no-op (the rest of `provision_device` re-keys and flushes nonces);
  different application -> raise with the conflicting `application_id`
  so the operator removes the device there instead of silently re-homing
  across paths (standalone vs esphome). `set_device_keys` gets the
  same INTERNAL/UNIQUE handling for the `device_keys.dev_eui` row, so a
  re-provision falls through to `UpdateKeys` the same way ALREADY_EXISTS
  did.
- **LoRaWAN: gRPC errors no longer hide behind a bare 500.** Every
  `ChirpStackClient` helper now wraps `grpc.RpcError` ->
  `ChirpStackUnavailable(_rpc_msg(exc))`, the same convention `ping()`
  already used. `/lorawan/provision-esphome`, `/lorawan/provision`,
  `/lorawan/activation`, and the codec endpoints already caught
  `ChirpStackUnavailable` -> 502; now they actually receive it, so a bad
  Bearer token surfaces as `502 "UNAUTHENTICATED:"` with the gRPC
  details visible in the response body instead of an unhandled 500 the
  UI couldn't explain. Triggered by a user-side debugging session: the
  pod had a stale token, the provisioning click 500'd silently, and
  reproducing it took digging through container logs to find the
  `_InactiveRpcError` the stack swallowed.

### Added

- **k8s manifest: ChirpStack provisioning envs.** `deploy/k8s.yaml` now
  wires `CHIRPSTACK_API_URL` (plain env, defaults to the in-cluster
  Service name `chirpstack:8080`) and `CHIRPSTACK_API_TOKEN` (optional
  secretKeyRef on `wirestudio-secrets`). A commented `CHIRPSTACK_API_TLS`
  entry covers the TLS-channel case. Closes the gap where `/lorawan/provision*`
  needed the operator to hand-add envs after every `kubectl apply`.
- **Provision dialog gates on `/lorawan/chirpstack/status`.** The
  external-component path's `LorawanProvisionEsphomeDialog` now probes
  ChirpStack reachability + auth on mount. When the probe returns
  `available: false`, the dialog renders an inline banner with the gRPC
  reason (plus a nudge that the Bearer token comes from the ChirpStack
  UI's **API Keys**, not the JWT signing secret -- the §11 footgun the
  setup doc warns about) and the Provision button stays disabled. Pairs
  with the wrap above: the banner shows the same `UNAUTHENTICATED:`
  string the click would otherwise have produced, but at dialog-open
  time, so the operator catches the misconfiguration before clicking.

### Changed

- **`deploy/k8s.yaml` image pin bumped `v0.12.0` → `v0.17.1`.** The
  standalone manifest's hardcoded image tag was five releases stale (the
  kustomize overlays roll forward, but the plain manifest doesn't).
- **`CHIRPSTACK_API_URL` default is now `chirpstack:8080`.** Was a
  specific LAN IP that meant something only on the original author's
  network; the new default is the typical in-cluster Service name and
  works out of the box for the k8s manifest. Non-k8s deploys still set
  the env explicitly.
- **Scrubbed local-environment specifics from `docs/lorawan/`.** Replaced
  real gateway hostname, private IP addresses, gateway silicon ID, and
  personal DNS names with documentation placeholders (`mygw`, `10.0.x.x`,
  `*.example.com`, `0000000000000000`). The setup snapshot keeps its
  structure but no longer leaks a single operator's network into a public
  repo.

## [0.17.1] — 2026-06-20

### Fixed

- **Inspector: editable JSON for object/array params.** The Inspector's
  `ParamForm` rendered scalar params (string/int/number/bool/enum)
  inline, but for `object` and `array` schemas it just stringified the
  value as read-only and showed "structured editing not yet supported."
  That left whole classes of params un-editable through the UI --
  `uart_gps.sensors` (the visible LoRaWAN-external-component blocker --
  sub-sensor IDs need to live here so `lorawan.payload` bindings can
  reference them), `pulse_counter.filters` / `count_mode`,
  `gpio_input.on_press` and the other `on_*` action lists. Now a JSON
  textarea per object/array param: parses on every keystroke and
  commits to the design only when the buffer is valid; kind-mismatched
  input (`[1,2]` on an `object` schema, `{"a":1}` on `array`) shows an
  inline parse error and doesn't commit; textarea auto-sizes 3-12 rows.
- **DesignPane: visible "stale" signal when render fails.** When the
  auto-debounced `/design/render` fails, the YAML/ASCII pane kept
  showing the prior successful render -- intentional context, but
  nothing visually flagged that the content was no longer current.
  Three coordinated signals: a rose dot on the ASCII / YAML tab labels
  (JSON stays clean since it reads design state directly), a sub-line
  on the "Render failed" banner naming the stale tab and pointing at
  the JSON tab for live state, and an `opacity-50` transition on the
  stale content itself. Surfaced during the LoRaWAN walkthrough: user
  edits weren't visibly ignored, but a series of small renderer
  rejections made it look that way.
- **`uart_gps` template: optional `params.sensors` guard.** The template
  referenced `(params.sensors or {}).items()` to default-empty when the
  user hadn't set the optional sensors map -- but that defense doesn't
  work under our `StrictUndefined` Jinja env: accessing
  `params.sensors` on a params dict without that key raises
  `UndefinedError` BEFORE the `or {}` evaluates, so the fallback never
  gets a chance. Symptom: adding `uart_gps` via the Inspector (which
  leaves `params: {}`) failed `/design/render` with 422
  `'dict object' has no attribute 'sensors'`. Switches to the standard
  `{%- if params.sensors is defined and params.sensors %}` guard used
  by `bme280` / `dht` / `sht3xd` / the phase-3 multi-channel sensors.
- **Pin solver: respect bus pin assignments.** `_used_gpio_pins` walked
  only `design.connections` for `kind: gpio` targets, but UART tx/rx,
  I2C sda/scl, SPI clk/miso/mosi/cs, I2S lrclk/bclk, and 1-wire pin
  live on the bus object itself (a component's bus connection target
  is `{kind: "bus", bus_id: "uart0"}` and doesn't carry the GPIO). So
  the solver treated bus pins as free. Symptom: design has UART on
  `tx=GPIO13`, user adds an HC-SR501 PIR with `OUT` unbound, solver
  picks `GPIO13` for `OUT` -- the same pin as UART tx. Now harvests
  bus pin slots into the used set.
- **Generator error hint: don't suggest "missing bus" for params
  errors.** The `UndefinedError` -> 422 converter blindly appended
  "Likely a missing bus connection" to every error message. That was
  a false friend when the actual error was a missing optional param
  (the `uart_gps.sensors` case above). Now differentiates: a
  `'dict object' has no attribute ...` error suggests the optional
  param / is-defined-guard fix; everything else still suggests the
  bus connection check.

## [0.17.0] — 2026-06-20

### Added

- **LoRaWAN: fleet push inlines per-device secrets.** `POST /fleet/push`
  gains an optional `lorawan_secrets: {dev_eui, join_eui, app_key}` body
  field; when present, the renderer substitutes literal values for the
  matching `!secret <name>` references in the `lorawan:` block, so the
  YAML the fleet stores carries the keys minted by
  `/lorawan/provision-esphome` without a separate write to the fleet's
  `secrets.yaml`. Any key not provided keeps its `!secret` reference; a
  request with `lorawan_secrets` against a non-LoRaWAN design is a no-op.
  The provision dialog gains a **"Push to fleet"** button next to the
  secrets block: provision → push → compile flows through one click, with
  the resulting filename + compile run id surfaced inline.
- **LoRaWAN: WebSerial DevEUI auto-derive (restored).** The provision
  dialog gains a "Detect from chip" button that reads the chip's eFuse
  MAC over WebSerial via the existing `detectChip()` + `macToEui64()`
  helpers and fills the DevEUI field. Disabled with a hint when WebSerial
  isn't available (e.g. Firefox / mobile). Manual entry remains the
  fallback; editing the field clears the detection hint.

### Changed

- **ADC component: `attenuation` value renamed `11db` -> `12db`.** ESPHome
  2024.5 renamed the value to match the actual ESP-IDF gain; `11db` still
  parses but emits a deprecation warning that surfaced as noise during the
  W2 `esphome config` gate. Behaviour is identical -- the same ESP-IDF setting
  is selected. Updates the `adc.yaml` template (params_schema enum + default
  + description), the two examples that pin a value explicitly
  (`analog-node`, `lorawan-battery-uplink`), the matching goldens, and the
  starter-design generator (`seed.py:_seed_battery_adc`). Verified by
  diffing goldens: the only golden change is the literal `11db -> 12db`
  swap on the two affected configs.

### Added

- **LoRaWAN workflow integration (W3 — orchestration endpoint).** New
  `POST /lorawan/provision-esphome` mints an AppKey, registers the device in
  ChirpStack against a path-specific device profile
  (`wirestudio-esphome-<region>-sub<n>`, distinct from the standalone path's
  per-component-set profiles), flushes its DevNonces, and returns the three
  keys in a `secrets:` block ready to drop into the `secrets.yaml` that
  rides next to the rendered ESPHome config. The AppKey is ephemeral --
  returned once, never persisted to `design.json` (CLAUDE.md rule). The
  endpoint gates on `design.lorawan.payload` being non-empty so a
  misrouted call against a standalone-path design fails with a clear 422.
  Codec setting (the JS decoder) is deferred to a follow-up endpoint so the
  device joins first; the new path's decoder is generated from
  `design.lorawan.payload`, not the standalone `codec.py`. DevEUI is the
  manual override field per the locked decision; the eFuse-MAC derivation
  over WebSerial is a separate iteration.

- **LoRaWAN workflow integration (W2 — generator emits the external-component
  block).** When `design.lorawan.payload` is non-empty, the YAML generator now
  emits an `external_components: - source: github://moellere/lorawan-for-esphome
  ref: <pinned>` block, the `lorawan:` config (region / sub_band / keys via
  `!secret` / radio config sourced from the board library's existing
  metadata), and one `sensor: - platform: lorawan, sensor: <id>` binding per
  payload field. Keys never enter `design.json` -- `dev_eui` / `join_eui` /
  `app_key` route through `Design.fleet.secrets_ref`. The radio block adapts
  to the chip family: SX127x boards emit dio0; SX126x boards emit dio1, busy,
  optional `tcxo_voltage`, and `dio2_as_rf_switch`. Worked example
  `lorawan-battery-uplink.json` (TTGO LoRa32 v1 + ADC battery, US915 sub-band
  2) -- the smallest design that exercises the full new path and can be
  hand-flashed against the live ChirpStack for the hardware-join test ahead
  of W3's orchestration UI. The standalone Arduino path is unaffected:
  emission is gated on `payload` non-empty, so existing non-LoRaWAN designs
  render byte-identical.

- **LoRaWAN workflow integration (W1 — `Design.lorawan` IR extension).** Adds
  the IR shape the external-component path needs: a `PayloadField` class
  (`{sensor: <component_id>}`) and an ordered `LoRaWAN.payload: list[...]`
  list -- the codec contract shared between the device's wire bytes and the
  ChirpStack `decodeUplink` decoder. Broadens `LoRaWAN.region` to accept
  US915 / EU868 / AU915 / AS923 (default still US915). The existing
  standalone-Arduino fields (`gps` / `dht22` / `oled` / `provisioning`) are
  untouched -- both paths share the block during the transition documented in
  `docs/lorawan/workflow-integration.md`. Schema mirrors. Pure IR addition,
  no generator branch yet (W2 wires that up).
- **Intent-to-device synthesis (phase 5 — condition gating).** An automation
  gains an optional `conditions: [...]` list; the trigger must fire AND every
  condition must hold for the actions to run. The generator wraps the action
  list in ESPHome's `if: { condition: ..., then: [...] }` form -- a single
  condition emits as an inline mapping, multiple conditions emit as a list
  (ESPHome's implicit AND). `CapabilityChecks` adds a `predicate -> esphome`
  mapping; 5 components gain `is_on` / `is_off` predicates that lower to
  `binary_sensor.is_on`, `switch.is_on`, or `light.is_on`: `gpio_input`,
  `gpio_output`, `ws2812b`, `hc-sr501`, `rcwl-0516`. The two motion sensors
  also gain an `id:` line in their binary_sensor template so condition
  predicates can reference them. New validator warnings:
  `automation_unknown_predicate` (predicate not in the component's checks),
  plus the existing `automation_unknown_component` /
  `automation_component_no_capability` codes now cover condition references.
  Worked example `guarded-button-light.json`: a button press toggles a light
  only when an enable switch is on. `design.json` schema gains
  `automations[].conditions`. The `sensor.in_range` predicate (single-output
  and multi-channel) is scoped separately because the multi-channel
  sub-sensor needs per-channel `id:` template surgery.

- **Intent-to-device synthesis (phase 4 — on_value_range threshold bounds).**
  An automation trigger gains optional `above` / `below` numeric bounds for the
  `on_value_range` event; the lowering wraps the action list in a
  `{above, below, then}` range entry, producing ESPHome's
  `on_value_range: - above: 28.0\n  then: [...]` shape. Two new permissive
  validator warnings (`automation_bounds_require_value_range`,
  `automation_value_range_needs_bounds`) catch the two cooperative mistakes
  -- bounds on the wrong event, or `on_value_range` with no bounds (which
  would fire on every reading). All 7 phase-3 multi-channel sensors (dht,
  bme280, bmp180, bmp280, aht10, htu21d, sht3xd) gain channel-tagged
  `on_value_range` provides and matching `params.<channel>_on_value_range`
  passthroughs in each sub-block, so a threshold trigger composes with the
  multi-channel selector. New worked example
  `temp-above-turns-on-fan.json` (bme280 temperature >= 28°C -> fan on).
  `design.json` schema gains `automations[].trigger.above` / `.below`.

- **Intent-to-device synthesis (phase 3 — multi-channel sensor triggers).**
  An automation trigger gains an optional `channel:` selecting which sub-block
  on a multi-output sensor it hangs off (e.g. `temperature` vs `humidity` on a
  bme280). Capability `provides` entries gain a matching `channel:` so the
  validator can check the trigger references a real (channel, event) pair, and
  the lowering combines them into a `<channel>_<event>` params key so the
  template's per-channel passthrough fires inside the right sub-block. Seven
  environmental sensors gain channel-tagged capability blocks and the matching
  `params.<channel>_on_value` passthroughs: `dht`, `bme280`, `bmp180`, `bmp280`,
  `aht10`, `htu21d`, `sht3xd`. New worked example `temp-turns-on-fan.json`
  exercises the path end-to-end (bme280 temperature -> switch). The validator's
  unknown-event warning now lists provides as `<channel>.<event>` pairs so the
  fix is obvious. `mpu6050` (7-channel IMU) replaces dht as the unannotated-
  component test fixture; the remaining unannotated multi-output components
  (power meters, the other IMU) carry too many channels to enumerate without
  a further design call. `design.json` schema gains
  `automations[].trigger.channel`.

- **Intent-to-device synthesis (phase 2 — value→transform→action).** An
  automation action gains an optional `transform` (action-arg name → a C++
  expression in terms of `x`, the value the trigger emits) that the generator
  lowers to an ESPHome `!lambda "return <expr>;"`. `rotary_encoder` gains
  `on_value` (kind=value) and the `uln2003` stepper gains `set_target`
  (→ `stepper.set_target`), wiring the canonical encoder→stepper case. New
  worked example `encoder-drives-stepper.json`: a knob's cumulative count
  drives the motor via `target: !lambda return (long) (x * 10);`, so each
  detent commands ten steps. The lambda rides the existing `params.on_*`
  `tojson` passthrough as a sentinel string and is restored to a tagged
  `!lambda` scalar after parse; the tag-quoting fixup keeps the body quoted
  when it isn't a plain-scalar-safe expression (a ternary, say). `design.json`
  gains `automations[].actions[].transform` in model + schema.

- **Intent-to-device synthesis (phase 1.5b — single-output sensor triggers).**
  Nine single-value sensors gain a `params.on_value` / `on_value_range`
  template passthrough plus a `role: sensor` `capability:` block, so a sensor
  reading can drive an automation: `ds18b20` (1-wire temperature), `bh1750` +
  `tsl2561` (lux), `vl53l0x` (ToF distance), `hx711` (load cell), `max31855`
  (thermocouple), `pulse_counter` (rate), `ads1115_channel` (ADC channel), and
  `tuya_sensor` (Tuya datapoint). `on_value` (kind=value) lowers a direct
  action list through the existing phase-1 path; `on_value_range` (kind=event)
  is declared for the threshold case that phase 2's richer trigger IR will
  carry the bounds for. Multi-channel sensors (`dht`, `bme280`, IMUs, power
  meters) stay unannotated: which sub-channel a trigger hangs off is a separate
  design call. Same evidence gate as 1.5a — every declared `provides.event` is
  tested against a real `params.<event>` passthrough — plus a lowering test
  proving a `ds18b20` `on_value` automation renders `switch.turn_on` into the
  sensor block.

- **Intent-to-device synthesis (phase 1.5a — wider library annotations).**
  Ten more library components gain `capability:` blocks so they can
  participate in `automations`: `hc-sr501` + `rcwl-0516` (motion sensors,
  on_press/on_release), `rc522` + `rdm6300` (RFID readers, on_tag /
  on_tag_removed), `rotary_encoder` (on_clockwise / on_anticlockwise; on_value
  with a transform lands in phase 2), `adc` + `hc-sr04` (analog input + ultrasonic
  distance, on_value / on_value_range), `rf_bridge` (on_code_received),
  `ws2812b` (light, both events + the standard `light.turn_on`/`turn_off`/
  `toggle` accepts), and `tuya_switch` (accepts side only — its template
  doesn't pass through the on_turn_on/off events yet). The annotation is
  evidence-grounded: each declared `provides.event` is gated by a test that
  the component's existing ESPHome template actually has a matching
  `params.<event>` passthrough (so an automation lowers into a key the
  renderer emits), and each `accepts.esphome` verb is gated against the
  known ESPHome platform prefixes (`switch.` / `light.` / `stepper.`).
  Adds a second worked example, `motion-turns-on-light.json` (PIR -> WS2812B
  via two automations on the on_press / on_release edges), proving the
  lowering generalises across capability pairs. Components without an `on_*`
  template passthrough (most of the bare-temperature/humidity sensors,
  displays, buses, hubs, cameras, PMICs, generic radios) stay unannotated --
  template-passthrough additions are phase 1.5b, scoped separately because
  template surgery has a different risk profile than additive metadata.



- **Intent-to-device synthesis (phase 1 — declarative event→action).** Adds a
  *functional* layer on top of the existing structural surface: library
  components gain an optional `capability:` block declaring their `role`
  (input / sensor / output / controller), the events they `provides`, and the
  actions they `accepts` with explicit ESPHome verbs. `design.json` gains an
  `automations: [{trigger, actions}]` graph parallel to the physical
  `connections` graph. The YAML generator lowers each automation onto the
  trigger component's `params.<event_key>` (extending any user-authored list,
  not replacing it), so the existing library templates render it as the right
  ESPHome trigger block — for the worked example
  (`button-toggles-light.json`), a press lowers to
  `on_press: [{switch.toggle: porch_light}]`. The `/design/validate` endpoint
  surfaces dangling refs as permissive warnings (`automation_unknown_component`,
  `automation_component_no_capability`, `automation_unknown_event`,
  `automation_unknown_action`) — half-authored automations don't block
  rendering, they just don't fire. Annotated `gpio_input` + `gpio_output` (the
  two components the worked example needs); the remaining ~58 library entries
  pick up annotations in phase 1.5. Value→transform→action (the encoder /
  stepper case) and a live `esphome config` authoring loop arrive in later
  phases per `docs/intent-to-device.md`.

- **Build-backend seam (framework axis, phase C — structural).** A
  `BuildBackend` protocol (`status` / `enqueue` / `stream` / `artifact`) now
  sits behind the LoRaWAN compile + firmware-download routes, with the in-pod
  PlatformIO worker wrapped as `LocalCompileBackend` and exposed via
  `LorawanTarget.build_backend()`. The endpoints no longer import the compile
  worker directly, so a *remote* LoRaWAN build worker (a build-agent pool, the
  way fleet-for-esphome pools esphome builds) drops in later as a second
  backend without touching the API — proven by a fake poll-style backend in the
  tests. No wire-API, frontend, or behavior change: one-at-a-time WebSerial
  flashing still streams the in-pod build exactly as before. (The job-id route
  guard is now backend-agnostic instead of hex-only, so a remote worker's
  handle addresses its artifact through the same `/lorawan/firmware/{id}`
  route.)

### Changed

- **LoRaWAN target: framework axis + library codegen blocks (phases A & B).**
  The four LoRaWAN sensors (GPS / AXP192 battery / DHT22 / OLED) were hardcoded
  into `codec.py` (`*_FIELDS` lists) and `main.cpp.j2`; they now live as
  per-component `lorawan:` codegen blocks in `library/components/*.yaml`
  (`lib_deps` / `requires` / `globals` / `setup` / `loop` / `fields` with HA
  hints). A single `codec.resolve_components()` assembles the design's
  components plus the board's onboard peripherals, and both the firmware
  generator and the codec build from that one inventory -- so expanding the
  LoRaWAN sensor set is now a library-file edit, at parity with ESPHome, and
  the payload/decoder stay in lockstep. `TargetPlugin` gains formal
  `generate()` + `component_ids()` and `/design/render` routes through the
  target. The uplink payload layout, ChirpStack `decodeUplink` + Home Assistant
  entities, and device-profile names are **unchanged** (byte-identical to
  0.16.0), so existing provisioned devices and HA entities are unaffected.

### Fixed

- **Power budget ignored the board's own draw.** Every Wi-Fi MCU's ~70-300 mA
  active current was invisible to the budget check; `LibraryBoard` had no
  current fields, and both budget callsites (`csp/pin_solver.py`,
  `generate/ascii_gen.py`) only summed `design.components`. Result: a bare D1
  Mini design reported `~0mA peak`. `LibraryBoard` now carries
  `current_ma_typical` + `current_ma_peak` (Wi-Fi associated active / TX burst,
  datasheet-sourced per MCU family with per-board overhead for USB-UART, LDO,
  status LEDs, onboard radios / displays / PMIC). All 23 bundled boards are
  annotated; both budget paths include the board's draw. Bumped
  `power.budget_ma` on the 24 examples whose budgets were silently low because
  the board was uncounted, and refreshed the ASCII goldens.

## [0.16.0] — 2026-06-14

### Fixed

- **LoRaWAN firmware boot-loop on TTGO LoRa32 (issue #80).** The TTGO
  `ttgo-lora32-v1`/`-v2` profiles declared the onboard SSD1306 reset on
  GPIO16. On these boards driving GPIO16 in the reset pulse wedges the chip
  at boot — *before* `Wire.begin()` — so the interrupt watchdog reboots it in
  a loop (`TG1WDT`), confirmed on hardware by serial bisection. The reset pin
  is dropped from both profiles (the template already skips the pulse when no
  reset pin is set; the SSD1306 self-resets on power-up). Heltec profiles keep
  their GPIO reset, which is correct there. The generated `main.cpp` also
  bounds the I2C bring-up (`Wire.setTimeOut` + ACK probe before
  `display.begin()`, `loop()` gated on `oledReady`) so an absent or
  differently-wired panel degrades gracefully rather than hanging.

### Added

- **`ttgo-lora32-v2` board profile** (LilyGO LoRa32 V2.1 / "T3 v1.6.1"),
  mapping to PlatformIO board `ttgo-lora32-v21`. Electrically identical to
  `ttgo-lora32-v1`; the distinct profile lets the most common "TTGO LoRa32"
  hardware select its matching board key.
- **Home Assistant entities from the LoRaWAN codec.** The generated ChirpStack
  codec now includes a `getHaDeviceInfo()` block alongside `decodeUplink`, so
  the [chirp2mqtt](https://github.com/modrisb/chirp) HA integration publishes
  MQTT-discovery entities for every payload field — temperature, humidity,
  battery (mV→V), GPS, link quality (RSSI/SNR) — with proper `device_class`/
  unit/`state_class`. GPS payloads (lat+lon) additionally emit a
  `device_tracker` whose latitude/longitude attributes drive the HA map. Each
  payload `Field` carries optional `ha_*` hints driving this. ChirpStack device
  profiles are also created with `auto_detect_measurements` enabled for
  ChirpStack's own metrics dashboards.

## [0.15.0] — 2026-06-11

### Added

- **Agent system payload slimmed (~10K tokens/turn) + `library_detail` tool.**
  The agent's system block now carries a **compact library index**
  (id / name / category / use_cases / aliases for components; id / name / mcu
  for boards) instead of dumping every full pydantic model. The full card
  (electrical metadata, `params_schema`, ESPHome template, KiCad block, pin
  definitions) loads on demand via a new `library_detail` tool — exposed on
  both the agent and the MCP server. Concrete win on 60 components: the
  library block drops from ~178 KB / ~44,500 tokens to ~23 KB / ~5,900 tokens
  per turn (**~87% reduction, ~38,600 tokens saved/turn**); the rest is
  fetched only when the agent actually needs it. The prompt cache still
  holds the slim block stable across turns.
- **Agent + MCP tool coverage for PCB and fab outputs.** The agent's tool
  surface and the MCP server gain `kicad_schematic`, `kicad_pcb` (returns a
  summary, not the megabyte board text), `fab_status`, `fab_bom`, and
  `fab_cpl` — so an agent (Claude Desktop / Claude Code over MCP, or the
  Anthropic API agent) can now drive design → board → BOM/CPL/Gerber-status
  end to end. Library-gated tools report `available: false` cleanly when the
  server doesn't have the KiCad libraries.
- **Fab outputs (Gerber / drill / CPL / BOM).** New `/design/fab/*` endpoints
  turn a design into a JLCPCB upload bundle: a **BOM** CSV (pure, grouped by
  part), a **CPL** pick-and-place CSV whose positions match the `.kicad_pcb`
  placement, and **Gerber + drill** via `kicad-cli` (gated like the schematic
  render). `POST /design/fab/package` zips all four. `GET /design/fab/status`
  reports what's available. Boards are unrouted until the Freerouting step, so
  the Gerbers carry pads but no traces — `is_routed`/status flag that. The
  KiCad export dialog gains a **Fab outputs** section (BOM / CPL / fab-package
  buttons, each gated on what the server supports). The `pcb-drc` CI tier also
  smoke-tests the Gerber export path.

## [0.14.0] — 2026-05-26

### Added

- **KiCad PCB export (`.kicad_pcb`).** A new `POST /design/kicad/pcb` emits a
  KiCad 8 board: every component + board footprint embedded from the pinned
  KiCad libraries and grid-placed, each pad bound to the net it shares in the
  design, plus an `Edge.Cuts` outline — no routing, so it opens in KiCad's PCB
  editor with a complete ratsnest ready to route (PCB layout, step 2; the
  footprint gate in 0.13.0 was step 1). Pad numbers resolve through the
  component's `kicad.pin_map` and symbol; generic connectors bind positionally.
  Reference designators and net names are shared with the schematic
  (`wirestudio/kicad/netlist.py`). Feature-gated like the schematic render —
  needs the footprint + symbol libraries on the server (`GET
  /design/kicad/pcb/status`); a `pcb-layout` CI gate proves every bundled
  example emits a structurally sound board, and a `pcb-drc` tier opens each
  board in real KiCad and runs DRC (unrouted airwires expected/ignored). The
  KiCad export dialog gains a **Download .kicad_pcb** button (gated on the
  server having the libraries). Freerouting autoroute and Gerber/CPL/BOM
  export remain on the path to 1.0.
- **Blank-board LoRaWAN flash.** The compile worker now also emits a merged
  factory image (bootloader + partitions + app via esptool `merge_bin` at the
  per-chip bootloader offset), served at `GET /lorawan/firmware/{key}/factory`.
  The flash dialog's **"Blank board — full flash"** toggle writes it at 0x0 with
  a full erase, for a board that's never been flashed; the default stays an
  app-region re-flash that preserves the bootloader + NVS DevNonces.
- **Local component inventory.** Track parts on hand in a single
  `inventory.json` (`GET`/`PUT`/`DELETE /inventory`), cross-check a design's
  BOM against it (`POST /design/inventory/check` → have / partial / need),
  and let the recommender prefer parts already in the drawer (`use_inventory`,
  a flat +5 boost). `INVENTORY_PATH` env override for the Docker `/data` volume.
  A web **Inventory** panel lists/adds/edits/removes entries and runs the BOM
  check against the open design (have / partial / need). Per-part low-stock
  thresholds (a `low` badge when on hand ≤ the reorder point) and CSV
  import/export (`GET /inventory/export.csv`, `POST /inventory/import`).
- **ULN2003 stepper driver** library component (28BYJ-48): ESPHome `stepper`
  platform on four control pins, with a KiCad footprint and a `blind-stepper`
  example (motorized blind) that round-trips through `esphome config`.
- **`-lorawan` Docker image.** CI builds and publishes a
  `wirestudio:<tag>-lorawan` variant (amd64) with PlatformIO + the `[lorawan]`
  extra baked in, so `/lorawan/compile` works in a deployment — the lean
  default image has no toolchain. Documented in [deployment](docs/deployment.md).

### Fixed

- **Dev deploy couldn't build LoRaWAN firmware.** The `bump-dev` job pinned
  the dev overlay to the lean `sha-<short>` image (no PlatformIO), so
  `/lorawan/compile` failed on the staging instance. The dev app now tracks
  the `-lorawan` variant (`bump-dev` waits on the `lorawan-image` job and
  writes the `-lorawan` tag), and the dev pod's memory limit is raised to 2Gi
  so the espressif32 link step doesn't OOMKill mid-build. Prod stays lean.
- **LoRaWAN GPS-on-console-UART footgun.** The flash dialog's external-GPS
  default was GPIO3/GPIO1 — U0RXD/U0TXD (the USB-serial console) on the classic
  ESP32, so a GPS there flooded the provisioning prompt with garbage and the
  device never joined. Default is now GPIO23/GPIO17, and the lorawan target's
  `validate()` warns (`lorawan_gps_on_console_uart`) when a GPS lands on the
  console UART.

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

[Unreleased]: https://github.com/moellere/wirestudio/compare/v0.40.0...HEAD
[0.40.0]: https://github.com/moellere/wirestudio/compare/v0.39.0...v0.40.0
[0.39.0]: https://github.com/moellere/wirestudio/compare/v0.38.0...v0.39.0
[0.38.0]: https://github.com/moellere/wirestudio/compare/v0.37.0...v0.38.0
[0.37.0]: https://github.com/moellere/wirestudio/compare/v0.36.0...v0.37.0
[0.36.0]: https://github.com/moellere/wirestudio/compare/v0.35.0...v0.36.0
[0.35.0]: https://github.com/moellere/wirestudio/compare/v0.34.0...v0.35.0
[0.34.0]: https://github.com/moellere/wirestudio/compare/v0.33.1...v0.34.0
[0.33.1]: https://github.com/moellere/wirestudio/compare/v0.33.0...v0.33.1
[0.33.0]: https://github.com/moellere/wirestudio/compare/v0.32.0...v0.33.0
[0.32.0]: https://github.com/moellere/wirestudio/compare/v0.31.0...v0.32.0
[0.31.0]: https://github.com/moellere/wirestudio/compare/v0.30.0...v0.31.0
[0.30.0]: https://github.com/moellere/wirestudio/compare/v0.29.0...v0.30.0
[0.29.0]: https://github.com/moellere/wirestudio/compare/v0.28.2...v0.29.0
[0.28.2]: https://github.com/moellere/wirestudio/compare/v0.28.1...v0.28.2
[0.28.1]: https://github.com/moellere/wirestudio/compare/v0.28.0...v0.28.1
[0.28.0]: https://github.com/moellere/wirestudio/compare/v0.27.2...v0.28.0
[0.27.2]: https://github.com/moellere/wirestudio/compare/v0.27.1...v0.27.2
[0.27.1]: https://github.com/moellere/wirestudio/compare/v0.27.0...v0.27.1
[0.27.0]: https://github.com/moellere/wirestudio/compare/v0.26.3...v0.27.0
[0.26.3]: https://github.com/moellere/wirestudio/compare/v0.26.2...v0.26.3
[0.26.2]: https://github.com/moellere/wirestudio/compare/v0.26.1...v0.26.2
[0.26.1]: https://github.com/moellere/wirestudio/compare/v0.26.0...v0.26.1
[0.26.0]: https://github.com/moellere/wirestudio/compare/v0.25.1...v0.26.0
[0.25.1]: https://github.com/moellere/wirestudio/compare/v0.25.0...v0.25.1
[0.25.0]: https://github.com/moellere/wirestudio/compare/v0.24.1...v0.25.0
[0.24.1]: https://github.com/moellere/wirestudio/compare/v0.24.0...v0.24.1
[0.24.0]: https://github.com/moellere/wirestudio/compare/v0.23.0...v0.24.0
[0.23.0]: https://github.com/moellere/wirestudio/compare/v0.22.0...v0.23.0
[0.22.0]: https://github.com/moellere/wirestudio/compare/v0.21.3...v0.22.0
[0.21.3]: https://github.com/moellere/wirestudio/compare/v0.21.2...v0.21.3
[0.21.2]: https://github.com/moellere/wirestudio/compare/v0.21.1...v0.21.2
[0.21.1]: https://github.com/moellere/wirestudio/compare/v0.21.0...v0.21.1
[0.21.0]: https://github.com/moellere/wirestudio/compare/v0.20.1...v0.21.0
[0.20.1]: https://github.com/moellere/wirestudio/compare/v0.20.0...v0.20.1
[0.20.0]: https://github.com/moellere/wirestudio/compare/v0.19.1...v0.20.0
[0.19.1]: https://github.com/moellere/wirestudio/compare/v0.19.0...v0.19.1
[0.19.0]: https://github.com/moellere/wirestudio/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/moellere/wirestudio/compare/v0.17.3...v0.18.0
[0.17.3]: https://github.com/moellere/wirestudio/compare/v0.17.2...v0.17.3
[0.17.2]: https://github.com/moellere/wirestudio/compare/v0.17.1...v0.17.2
[0.17.1]: https://github.com/moellere/wirestudio/compare/v0.17.0...v0.17.1
[0.17.0]: https://github.com/moellere/wirestudio/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/moellere/wirestudio/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/moellere/wirestudio/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/moellere/wirestudio/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/moellere/wirestudio/compare/v0.11.0...v0.13.0
[0.11.0]: https://github.com/moellere/wirestudio/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/moellere/wirestudio/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/moellere/wirestudio/releases/tag/v0.9.0
