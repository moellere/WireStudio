# wirestudio

Agent-driven IoT device design tool. Describe a goal (or pick parts);
get ESPHome YAML, an ASCII wiring diagram, and a BOM that compile
under upstream ESPHome.

Produces ESPHome configs but is not affiliated with the ESPHome
project — see [`weirded/fleet-for-esphome`](https://github.com/weirded/fleet-for-esphome)
for the OTA-deploy companion this studio's **Push to fleet** flow
talks to.

## Status

`v0.9.0` — first tagged release. The studio has wide surface area
(YAML, schematic, enclosure, agent, fleet handoff, web UI) and a
narrow set of things actually verified against upstream tools. This
section is honest about which is which, ordered by how much it
matters that it works.

Tiers, in priority order:

| Tier | Area | What it does | Verified by |
|---|---|---|---|
| **Verified** | ESPHome YAML production | render `design.json` → ESPHome YAML | `esphome config` passes on every bundled example, every PR ([gate](.github/workflows/esphome-config.yml)); nightly `esphome compile` smoke against a representative example ([compile](.github/workflows/esphome-compile.yml)) |
| **Verified** | CSP pin solver + compat checker | assign legal pins, surface boot-strap / ADC2-WiFi / voltage / locked-pin issues | unit tests + property checks in `tests/test_pin_solver.py` + `tests/test_compatibility.py` |
| **Verified** | Fleet handoff | push YAML to `distributed-esphome` ha-addon, optional compile + log relay | round-trip tests in `tests/test_fleet.py` |
| **Works (lighter checks)** | KiCad schematic | emit a SKiDL Python script the user runs locally | unit tests assert the script is well-formed Python with expected nets; **not** verified by opening in KiCad |
| **Works (lighter checks)** | Parametric enclosure | OpenSCAD `.scad` from board mount-hole metadata | unit tests + manual-print iteration; not verified by an OpenSCAD parser in CI |
| **Experimental** | Thingiverse search relay | rank community models for a board | smoke-tested; depends on a third-party search API that ranks unevenly |
| **Experimental** | Agent (Claude tool-using) | natural-language design driving | works in practice; tool surface is small; no auto-eval against task list yet |
| **Deferred** | KiCad PCB layout | Freerouting + Gerber + JLCPCB CPL/BOM | 1.0+, not started |

The **Verified** tier is the bar the project is asking to be judged
on. Everything else is offered with the caveat that's spelled out in
the table.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the bar a change has to
clear before merging, [`CHANGELOG.md`](CHANGELOG.md) for per-release
deltas, and [`START.md`](START.md) for the longer-form design notes.

Tested against ESPHome **`==2025.12.7`** (pinned in
`.github/workflows/esphome-config.yml` + bumped deliberately). When
that pin moves, this line moves with it.

## What it does

- **Design.** Web UI inspector (board, fleet metadata, components,
  buses, connections, requirements, warnings). Add components by
  picking a capability (**Add by function**) — the recommender ranks
  library matches against use cases. Drag-and-drop pinout for
  component-to-board pin assignment. Pin locks per role. Bus editor
  with rename propagation + inline compatibility warnings. USB
  bootstrap from a plugged-in ESP via WebSerial + esptool-js. Saved
  designs at `designs/<id>.json` with a **Saved** tab + **New design**
  dialog.
- **Validate.** CSP pin solver assigns every unbound connection with
  capability-aware fallback (boot strap pins de-prioritised; ADC1
  preferred over ADC2 on classic ESP32). Port-compatibility checker
  flags input-only-as-output errors, boot-strap risks, serial console
  reuse, voltage limits, ADC2/WiFi conflicts, locked-pin mismatches.
  Strict mode (header toggle) promotes warn/error compat to render
  errors as a pre-deploy gate.
- **Generate.** Pure functions over `design.json` + the static
  library produce ESPHome YAML, ASCII wiring diagrams + BOM, a
  parametric OpenSCAD enclosure (`.scad`), and a SKiDL Python script
  the user runs locally to produce a `.kicad_sch`. Bundled examples
  pinned as goldens.
- **Deploy.** **Push to fleet** ships the YAML to a running
  [`weirded/distributed-esphome`](https://github.com/weirded/distributed-esphome)
  ha-addon over Bearer-token HTTP; optional `compile: true` enqueues
  an OTA build with live log streaming (Server-Sent Events). **Strict
  mode** refuses the push when warn/error compat issues remain.
- **Discover enclosures.** Generate a parametric `.scad` shell from
  the board's mount-hole + USB-port metadata, or search community
  models on Thingiverse (`THINGIVERSE_API_KEY`).
- **Self-host.** Single multi-arch Docker image
  (`linux/amd64` + `linux/arm64`). FastAPI serves API + SPA from one
  process. Kubernetes manifest, docker-compose recipe, and an nginx
  production layout in [`deploy/`](deploy/).

## Quickstart

### Docker (single-image deployment)

```sh
docker run --rm -p 8765:8765 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v wirestudio-data:/data \
  ghcr.io/moellere/wirestudio:v0.9.0
```

Open <http://localhost:8765>. The image bundles the FastAPI server +
the built web UI in one process; `/api/*` is the JSON API,
`/` is the SPA. `/data` holds the agent's session log + saved
designs across upgrades.

Available tags:

| Tag | What it tracks |
|---|---|
| `:v0.9.0` / `:0.9.0` / `:0.9` / `:latest` | the v0.9.0 release |
| `:main` | latest commit on `main` (rolling) |
| `:sha-<short>` | a specific commit |

All four feature-gating env vars are optional — the studio runs
without any of them, just with the corresponding feature turned off:

| Env var | What it gates |
|---|---|
| `ANTHROPIC_API_KEY` | the agent (`/agent/*` endpoints + the chat sidebar) |
| `FLEET_URL` + `FLEET_TOKEN` | distributed-esphome push (`/fleet/*`) |
| `THINGIVERSE_API_KEY` | enclosure search (`/enclosure/search`) |

For Kubernetes, see [`deploy/k8s.yaml`](deploy/k8s.yaml). For an
nginx-front compose recipe, see [`deploy/README.md`](deploy/README.md).

### CLI

```sh
pip install -e .[dev]
python -m wirestudio.generate examples/garage-motion.json
```

Prints rendered YAML and the ASCII wiring block to stdout. To write to files:

```sh
python -m wirestudio.generate examples/garage-motion.json \
    --out-yaml build/garage-motion.yaml \
    --out-ascii build/garage-motion.txt
```

### HTTP API

```sh
python -m wirestudio.api                    # localhost:8765
python -m wirestudio.api --reload           # dev mode (auto-reload on edits)
```

Browse the auto-generated OpenAPI docs at <http://127.0.0.1:8765/docs>.

To enable the **agent** endpoints (`/agent/turn`, `/agent/sessions/{id}`),
export an Anthropic API key before starting the server:

```sh
export ANTHROPIC_API_KEY=sk-ant-...
python -m wirestudio.api
```

Without a key, `/agent/status` reports `available: false` and the agent
sidebar in the UI shows a friendly notice instead of trying to talk.

To enable the **fleet handoff** (`/fleet/push` and the **Push to fleet**
header button), point the API at a running distributed-esphome ha-addon:

```sh
export FLEET_URL=http://homeassistant.local:8765
export FLEET_TOKEN=$(grep -oP '(?<=token: )\S+' .../addon/secrets.yaml)
python -m wirestudio.api
```

`GET /fleet/status` reports `available: true` when both env vars are set
and the addon answers a probe; otherwise the UI surfaces the specific
reason (URL missing, unauthorized, unreachable).

### Web UI (dev)

```sh
# In one terminal:
python -m wirestudio.api

# In another:
cd web && npm install && npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api/*` to the studio API,
so no CORS plumbing in dev. The same web UI is served at `/` from the
production Docker image; the dev server is only useful when you're
editing UI code yourself.

Inspector surfaces:

- **Design pane** — board picker, fleet metadata (device_name, tags,
  secrets refs), requirements, warnings, components list (add /
  remove with auto-wiring), buses (add / rename / edit pin slots /
  remove), per-bus + design-level compatibility warnings.
- **Component-instance pane** — params (form generated from each
  library entry's `params_schema`), connections (per-row editor with
  rail / gpio / bus / expander_pin / component target kinds),
  Form ⇄ Pinout view toggle for drag-and-drop pin assignment, 🔓/🔒
  per-row pin lock.

Header buttons: **New design**, **Reset**, **Save**, **Download JSON**,
**Solve pins**, **strict** (toggle), **Connect device** (USB
bootstrap), **Add by function** (capability picker), **Schematic**
(KiCad export), **Enclosure** (parametric `.scad` + Thingiverse
search), **Push to fleet**.

Useful endpoints:

| Method | Path | What it does |
|---|---|---|
| `GET`  | `/library/boards` | summaries of every board in the library |
| `GET`  | `/library/boards/{id}` | full board, including pinout |
| `GET`  | `/library/components?category=&use_case=&bus=` | filtered component summaries |
| `GET`  | `/library/components/{id}` | full component, including ESPHome template |
| `GET`  | `/library/use_cases` | distinct capabilities across the library, with counts; powers the **Add by function** picker |
| `POST` | `/library/recommend` | rank library components against a free-text or capability query |
| `POST` | `/design/validate` | parse a `design.json`, return summary or 422 |
| `POST` | `/design/render` | parse + render a `design.json` to `{yaml, ascii}` |
| `POST` | `/design/enclosure/openscad` | generate a parametric `.scad` shell for the design's board |
| `POST` | `/design/kicad/schematic` | generate a SKiDL Python script the user runs locally to produce a `.kicad_sch` |
| `GET`  | `/enclosure/search?library_id=...&query=...` | search community-uploaded enclosure models (Thingiverse) |
| `GET`  | `/enclosure/search/status` | per-source availability + configure hints |
| `GET`  | `/examples` | list bundled examples |
| `GET`  | `/examples/{id}` | fetch an example as raw `design.json` |
| `GET`  | `/fleet/status` | check whether `FLEET_URL` + `FLEET_TOKEN` reach a distributed-esphome ha-addon |
| `POST` | `/fleet/push` | render `design.json` and push it as `<device_name>.yaml` (optionally `compile: true`) |
| `GET`  | `/fleet/jobs/{run_id}/log?offset=N` | poll the addon's build log for a compile run; returns `{log, offset, finished}` |
| `GET`  | `/fleet/jobs/{run_id}/log/stream` | Server-Sent Events relay over the same log endpoint; ~300ms cadence, exits with `event: done` when the build finishes |

The HTTP API is a thin layer over the studio's pure-function modules
(`wirestudio.generate`, `wirestudio.csp`, `wirestudio.recommend`, `wirestudio.fleet`,
`wirestudio.enclosure`, `wirestudio.kicad`). Server state is limited to the
agent session log + the saved-design store — both file-backed under
`/data` (via `SESSIONS_DIR` / `DESIGNS_DIR`). Permissive CORS for
`localhost:5173` / `localhost:3000` so the dev Vite server can hit
it without a proxy.

## Examples

| Example | Board | What it is |
|---|---|---|
| [`garage-motion.json`](examples/garage-motion.json) | ESP32-DevKitC-V4 | PIR + BME280 (temp/humidity/pressure) over I2C |
| [`awning-control.json`](examples/awning-control.json) | WeMos D1 Mini | Cover controller — 4 limit switches + buttons via MCP23008 expander, 2 GPIO relays, dual-PWM motor drive |
| [`wasserpir.json`](examples/wasserpir.json) | WeMos D1 Mini | Single PIR with a scheduled nightly reboot |
| [`oled.json`](examples/oled.json) | WeMos D1 Mini | SSD1306 status display rendering time, date, IP |
| [`bluemotion.json`](examples/bluemotion.json) | WeMos D1 Mini | PIR + WS2812B NeoPixel; motion lights the LED |
| [`distance-sensor.json`](examples/distance-sensor.json) | NodeMCU v2 | HC-SR04 ultrasonic + WS2812B NeoPixel; LED color tracks distance |
| [`securitypanel.json`](examples/securitypanel.json) | WeMos D1 Mini | 12 door/window/motion sensors via MCP23017 expander, RTTTL piezo, GPIO siren |
| [`rc522.json`](examples/rc522.json) | WeMos D1 Mini | MFRC522 RFID reader (SPI), NeoPixel status LED, RTTTL piezo, manual button |
| [`esp32-audio.json`](examples/esp32-audio.json) | NodeMCU-32S | I2S audio (MAX98357A DAC) + ST7789V SPI dashboard display, Arduino framework |
| [`bluesonoff.json`](examples/bluesonoff.json) | ESP-01S 1MB | Sonoff Basic relay; front button (boot strap pin) toggles a single GPIO relay |
| [`wemosgps.json`](examples/wemosgps.json) | WeMos D1 Mini | UART GPS module — lat/lon/altitude/speed/satellites + runtime baud-rate selector |
| [`ttgo-lora32.json`](examples/ttgo-lora32.json) | TTGO LoRa32 V1 | ESP32 + onboard SX1276 LoRa radio + onboard SSD1306 OLED + battery ADC, ESP-IDF |
| [`multi-temp.json`](examples/multi-temp.json) | WeMos D1 Mini | Two DS18B20 temp sensors sharing a single 1-wire bus + an RCWL-0516 microwave motion sensor |
| [`room-climate.json`](examples/room-climate.json) | WeMos D1 Mini | BH1750 ambient-light + AHT20 temp/humidity on one I2C bus |
| [`desk-climate.json`](examples/desk-climate.json) | ESP32-C3-DevKitM-1 | Sensirion SHT3x precision temp/humidity over I2C |
| [`parking-distance.json`](examples/parking-distance.json) | NodeMCU v2 | VL53L0X laser ToF distance (indoor parking-spot indicator) |
| [`keypad.json`](examples/keypad.json) | WeMos D1 Mini | 8 buttons read through a PCF8574 GPIO expander over I2C |
| [`smart-plug.json`](wirestudio/examples/smart-plug.json) | ESP8285 1MB | Athom-style smart plug — relay + button + CSE7766 AC power metering over UART 4800 8E1 |
| [`smart-plug-v1.json`](wirestudio/examples/smart-plug-v1.json) | ESP8285 1MB | Older Athom v1 / Sonoff POW R1 plug — same topology with the HLW8012 / BL0937 3-pin pulse meter |
| [`desk-matrix.json`](wirestudio/examples/desk-matrix.json) | ESP32-DevKitC | 8x8 WS2812 matrix driven by the ESP32 RMT peripheral (no bit-banging) |
| [`rs485-energy.json`](wirestudio/examples/rs485-energy.json) | ESP32-DevKitC-V4 | Eastron SDM230 single-phase energy meter via Modbus RTU (UART2 + MAX485 transceiver, GPIO5 drives DE+RE) |
| [`bl0906-mainmeter.json`](wirestudio/examples/bl0906-mainmeter.json) | ESP32-DevKitC-V4 | BL0906 6-channel CT-clamp energy monitor over UART2 (Athom EM6-style whole-home sub-metering) |
| [`nextion-thermostat.json`](wirestudio/examples/nextion-thermostat.json) | ESP32-DevKitC-V4 | Nextion HMI thermostat panel — display on UART2 + SHT3xD temp/humidity on default I2C |
| [`tuya-smart-plug.json`](wirestudio/examples/tuya-smart-plug.json) | ESP8285 1MB | Tuya-MCU smart plug — relay (DP 1) + power (DP 17) + energy (DP 18) over UART 9600; logger off UART0 |
| [`weather-station.json`](wirestudio/examples/weather-station.json) | ESP32-DevKitC-V4 | BMP280 barometer + HTU21D temp/humidity + TSL2561 lux on one shared I2C bus |
| [`attic-logger.json`](wirestudio/examples/attic-logger.json) | WeMos D1 Mini | DHT22 single-wire temp/humidity + legacy BMP180 I2C barometer |

Generated artifacts for each are pinned as goldens in
[`tests/golden/`](tests/golden/). For a per-component / per-board view of
which library entries are exercised by these examples, see
[`docs/library-coverage.md`](docs/library-coverage.md) (regenerate with
`python scripts/coverage_matrix.py`).

## Architecture

```
   design.json  ── single source of truth (JSON-Schema-validated)
        │
        ▼
  ┌─ wirestudio.model         pydantic models mirroring the schema
  ├─ wirestudio.library       loads boards/ + components/ YAML
  ├─ wirestudio.generate      design + library → ESPHome YAML + ASCII
  ├─ wirestudio.csp           pin solver + port-compatibility checker
  ├─ wirestudio.recommend     deterministic capability ranking
  ├─ wirestudio.agent         Claude tool-using agent + session store
  ├─ wirestudio.designs       file-backed designs/<id>.json store
  ├─ wirestudio.fleet         distributed-esphome HTTP client
  ├─ wirestudio.enclosure     parametric OpenSCAD + Thingiverse search
  ├─ wirestudio.kicad         SKiDL Python script emitter
  └─ wirestudio.api           FastAPI HTTP layer (mounts everything above)
                          serve.py adds the production wrapper:
                          API at /api/*, web bundle at /
```

Generators are pure functions of `design.json` + the static library — no
artifact-to-document round-trips. Library files in `library/components/`
carry the electrical metadata ESPHome doesn't (pin roles, voltage ranges,
current draw, decoupling caps, pull-up requirements) plus a Jinja2 template
that renders the ESPHome YAML for that component, an `enclosure:` block
the OpenSCAD generator reads, and a `kicad:` block the schematic exporter
reads.

## Library

Currently shipped:

**Boards** (`library/boards/`)
- `esp32-devkitc-v4` — ESP32 DevKitC V4 (ESP32-WROOM-32, 4MB flash)
- `nodemcu-32s` — NodeMCU-32S (ESP32-WROOM-32, marks I2S-capable pins)
- `ttgo-lora32-v1` — LilyGO TTGO LoRa32 V1 (ESP32 + onboard SX1276 + onboard SSD1306)
- `ttgo-t-beam` — LilyGO TTGO T-Beam v1.x (ESP32 + onboard SX1276 + NEO-6M GPS + AXP192 PMIC + 18650)
- `esp32-c3-devkitm-1` — ESP32-C3-DevKitM-1 (single-core RISC-V, USB-Serial-JTAG, onboard WS2812)
- `esp32-s3-devkitc-1` — ESP32-S3-DevKitC-1 (dual-core Xtensa, native USB, onboard WS2812)
- `esp32cam-ai-thinker` — AI-Thinker ESP32-CAM (ESP32-WROVER-B + OV2640 + microSD)
- `esp32-wrover-cam` — ESP32-WROVER-CAM (Freenove-style, OV2640 with the WROVER pinout)
- `m5stack-atom` — M5Stack Atom Lite / Echo (ESP32-PICO-D4, 24mm cube, onboard SK6812)
- `m5stack-atoms3` — M5Stack AtomS3 (ESP32-S3 + onboard 0.85" 128×128 ST7789 + IMU)
- `wemos-d1-mini` — WeMos D1 Mini (ESP-12F module, ESP8266)
- `nodemcu-v2` — NodeMCU v2 (ESP-12E/F module, ESP8266, breaks out RX/TX/MISO/MOSI as D9-D12)
- `esp01_1m` — ESP-01S 1MB module / Sonoff Basic-class devices
- `esp8285-1m` — Generic ESP8285 1MB SoC (Athom / Sonoff Basic R3+ / Tuya smart plugs)

**Components** (`library/components/`)

_Environmental sensors:_
- `bme280` — Bosch temperature/humidity/pressure sensor (I2C)
- `bmp180` — Bosch BMP180/BMP085 barometric pressure + temperature (I2C)
- `bmp280` — Bosch temperature/pressure sensor (I2C, no humidity)
- `dht` — DHT11 / DHT22 / AM2302 temperature + humidity (single-wire)
- `htu21d` — TE Connectivity HTU21D temperature + humidity (I2C; covers Si7021 / SHT2x)
- `sht3xd` — Sensirion SHT3x / SHT4x precision temp + humidity (I2C; modern default)
- `aht10` — Aosong AHT10 / AHT20 cheap temp + humidity (I2C; AliExpress weather modules)
- `ds18b20` — Dallas DS18B20 1-Wire temperature sensor (single-pin bus + 4.7kΩ pull-up)
- `bh1750` — BH1750FVI ambient light sensor in lux (I2C; GY-30 / GY-302 modules)

_Specialty sensors:_
- `max31855` — Maxim K-type thermocouple amplifier (SPI; -270..+1372°C)
- `hx711` — AVIA 24-bit load-cell ADC (custom 2-wire serial)
- `tsl2561` — AMS ambient light sensor (lux, I2C)
- `mpu6050` — InvenSense 6-axis IMU (3-axis accel + 3-axis gyro + die temp, I2C)

_Presence / distance:_
- `hc-sr04` — ultrasonic distance sensor (4-pin: VCC, GND, TRIGGER, ECHO)
- `hc-sr501` — PIR motion sensor (used as a generic PIR)
- `rcwl-0516` — microwave doppler motion sensor (low-power PIR alternative)
- `ld2420` — Hi-Link LD2420 24GHz mmWave presence sensor (UART)
- `vl53l0x` — STMicro VL53L0X laser time-of-flight distance (I2C; indoor up to ~1.2m)

_RFID / radios:_
- `rc522` — MFRC522 RFID reader (SPI, singleton)
- `rdm6300` — RDM6300 125kHz EM4100 RFID reader (UART, singleton)
- `sx127x` — Semtech SX1276/SX1278 LoRa radio (SPI, singleton)
- `cc1101` — TI CC1101 sub-GHz transceiver (SPI, singleton)
- `rf_bridge` — Sonoff RF Bridge 433MHz EFM8 module (UART, singleton)

_Displays:_
- `ssd1306` — 128×64 OLED (I2C)
- `st7789` — Sitronix ST7789V color TFT (SPI write-only)
- `ili9xxx` — ILI9341 / ILI9486 / ILI9488 SPI TFT
- `lcd_pcf8574` — HD44780 16x2 / 20x4 LCD via PCF8574 I2C backpack
- `tm1638` — TM1638 8-digit 7-segment + 8 LEDs + 8 buttons combo
- `max7219` — MAX7219 7-segment / 8x8 LED matrix driver (SPI)

_Touch / input:_
- `xpt2046` — XPT2046 resistive touchscreen controller (SPI)
- `rotary_encoder` — Quadrature rotary encoder (KY-040 style)

_IO expanders + ADC hubs:_
- `mcp23008` — 8-bit I2C GPIO expander (Microchip)
- `mcp23017` — 16-bit I2C GPIO expander (Microchip)
- `pcf8574` — NXP PCF8574 / PCF8575 8-/16-bit I2C GPIO expander (cheap, weak open-drain)
- `ads1115` — TI 4-channel 16-bit ADC (I2C) hub; rescues ESP32 designs from the ADC2/WiFi conflict
- `ads1115_channel` — one logical reading on an ADS1115 hub (multiplexer + gain + update_interval per channel)

_Generic IO:_
- `gpio_input` — generic binary_sensor on a GPIO or expander pin (buttons, limit switches, door/window/motion sensors)
- `gpio_output` — generic switch on a GPIO or expander pin (relays, indicators)
- `adc` — generic analog input (battery monitoring, potentiometers, LDRs)
- `pulse_counter` — pulse counter / tachometer (RPM, flow, energy meters)

_Light / audio / camera:_
- `ws2812b` — WS2812B / SK6812 addressable RGB LED (1-wire NeoPixel; bit-banged or ESP8266-DMA)
- `esp32_rmt_led_strip` — same WS2812 / SK6812 silicon, ESP32 RMT-driven (preferred on ESP32 / S2 / S3 / C3)
- `apa102` — APA102 / SK9822 addressable RGB strip (DotStar, SPI-style)
- `max98357a` — Maxim Class-D mono I2S amp + DAC
- `rtttl` — piezo buzzer + RTTTL melody player (PWM output)
- `esp32_camera` — ESP32 OV2640 / OV7670 / OV5640 camera

_Power metering:_
- `cse7766` — Chipsea AC voltage / current / power / energy over UART 4800 8E1 (Athom v2/c3 + Sonoff plugs)
- `hlw8012` — HLW8012 / BL0937 / CSE7759 AC power meter via 3-pin pulse interface (older Athom v1 + Sonoff POW R1)
- `bl0906` — Belling 6-channel AC energy meter over UART 19200 (Athom EM6 / whole-home sub-metering)
- `modbus` + `sdm_meter` — Modbus RTU bus (RS485 via MAX485 transceiver) + Eastron SDM120/220/230/630 single/three-phase DIN-rail meter

_Vendor bridges:_
- `tuya` + `tuya_switch` + `tuya_sensor` — Tuya MCU UART bridge plus per-datapoint switch and sensor platforms (smart plugs / switches / climate gadgets that ship with an ESP8266-class radio talking to a separate Tuya MCU)

_Displays (HMI):_
- `nextion` — Nextion HMI smart display over UART 9600 (T/K/P series; .tft uploaded separately via Nextion Editor)

_Location:_
- `uart_gps` — generic UART GPS module (NEO-6M / NEO-8M)

The `gpio_input` / `gpio_output` components and the `kind: expander_pin`
connection target together let downstream platforms hang off any expander
without bloating `esphome_extras`. See `examples/securitypanel.json` for a
12-sensor MCP23017 wiring or `examples/awning-control.json` for a mix of
expander inputs and outputs.

The library now spans the device classes used across the
[`moellere/esphome`](https://github.com/moellere/esphome) device
configurations (camera boards, mmWave presence, sub-GHz radios,
character LCDs, touchscreens, generic ADC and pulse counters,
addressable LEDs, RTTTL piezo, RFID variants, and the M5Stack /
ESP32-C3 / ESP32-S3 board family). It will keep growing as new device
configs land. See
[`START.md` § Library sourcing strategy](START.md#library-sourcing-strategy)
for the hybrid plan.

## Layout

```
schema/                  JSON Schema for design.json (source of truth)
library/boards/          board manifests (pinout, rails, framework, enclosure, kicad)
library/components/      component manifests (electrical + ESPHome + enclosure + kicad)
wirestudio/                  python package — see Architecture above for the module map
web/                     React 19 + Vite + Tailwind v4 SPA
examples/                bundled design.json files (every one pinned by goldens)
tests/                   pytest + golden artifacts; vitest tests under web/src
deploy/                  k8s.yaml, docker-compose.yml, nginx.conf for self-hosting
Dockerfile               multi-stage build for the published GHCR image
.github/workflows/       GHA workflow that publishes ghcr.io/.../wirestudio
scripts/                 dev helpers (currently: examples → `esphome config` gate)
CHANGELOG.md             per-release feature deltas
START.md                 vision, decisions, phase plan
CLAUDE.md                working conventions for both Claude and humans
CONTRIBUTING.md          substantive bar a change has to clear (the YAML gate, etc.)
```

## Tests

```sh
python -m pytest                          # ~297 cases, ~10s
python -m ruff check .                    # lint
cd web && npx vitest run                  # ~125 cases, ~5s (vitest + jsdom)
pip install 'esphome==2025.12.7'
python scripts/check_examples.py          # the YAML gate -- every example through `esphome config`
python scripts/check_examples.py --compile garage-motion    # the compile-smoke; slow (~10min cold)
```

The `esphome config` gate is the headline test: it renders every
bundled example through the studio and runs upstream ESPHome's own
validator against the output. Anything the studio emits has to
round-trip through that gate, and the GitHub Actions workflow
([`.github/workflows/esphome-config.yml`](.github/workflows/esphome-config.yml))
runs it on every PR. A nightly compile-smoke
([`.github/workflows/esphome-compile.yml`](.github/workflows/esphome-compile.yml))
goes one level deeper -- it runs `esphome compile` against a
representative example so we catch upstream toolchain / codegen
regressions even when no code has changed.

To run the same gate before every push, install the pre-commit
hooks once:

```sh
pip install pre-commit
pre-commit install --hook-type pre-push
```

After that, `git push` runs the gate locally and aborts on failure.

Golden tests pin the generator output for every bundled example.
Regenerate goldens with the CLI when output legitimately changes;
commit the new files in the same diff as the code change. The web
suite covers `lib/design.ts` plus React components (BusList,
ConnectionForm, EnclosureDialog, Inspector, CapabilityPickerDialog,
PinoutView, PushToFleetDialog, SchematicDialog) via React Testing
Library + jsdom; network surfaces are mocked at the api/client
boundary so the suite stays offline.

The GitHub Actions workflow runs the YAML gate + the full suite +
multi-arch image build on every PR + merge to main.

## Roadmap

Reorganised by priority — what's worth working on next, ordered by
how much it raises the floor on whether the studio is actually
useful. The previous "ship more surface area" roadmap is preserved
in [`CHANGELOG.md`](CHANGELOG.md) (per-release deltas) and
[`START.md`](START.md) (decisions + phase scope).

**Priority 1 — YAML production correctness.** *Active.* The single
non-negotiable bar: every artifact the studio emits round-trips
through upstream `esphome config`. Done so far: `esphome config` CI
gate over every bundled example; pinned ESPHome version called out
in this README + workflow; CONTRIBUTING.md establishes the gate as
the merge bar. Next: real `esphome compile` smoke for one example;
component-coverage matrix (which components have an example that
validates) so additions are forced through the gate.

**Priority 2 — Wiring schema correctness.** *Verified-light.* SKiDL
emitter + 100% library `kicad:` coverage shipped. Honest gap: the
output is unit-tested as Python text, not opened in KiCad. Next:
container-side KiCad CLI in CI to actually open + render the
generated schematic; pin-solver property tests on randomized
designs; compatibility-checker fuzzing.

**Priority 3 — Enclosures.** *Lower priority.* Parametric OpenSCAD
generator + Thingiverse search relay shipped. Open question: keep
investing here, or outsource to e.g.
[YAPP_Box](https://github.com/mrWheel/YAPP_Box) and integrate
instead of reimplementing? Decision deferred until P1 + P2 are
tighter.

**Priority 4 — PCB layout.** *Deferred to 1.0+.* No work in flight;
not adding surface here until P1 is rock solid.

**Plumbing — already shipped.** API (`0.2`), web UI (`0.3` +
`0.6+`), USB bootstrap (`0.4`), agent (`0.5` + streaming), CSP
solver (`0.6`), fleet handoff (`0.7`), enclosure (`0.8`), KiCad
schematic (`0.9`), Docker single-image deploy + K8s manifest. See
[`CHANGELOG.md`](CHANGELOG.md) for the per-release feature deltas.

**Future** — multi-writer state backend so the studio can run as a
HA replica; agent eval harness against a task list; ESPHome version
matrix in CI (last 2 stables) so we can call out which components
work where.

## Contributing

[`CONTRIBUTING.md`](CONTRIBUTING.md) is the substantive bar — what
"working" means for the artifacts the studio produces, including
the `esphome config` gate every PR has to clear. [`CLAUDE.md`](CLAUDE.md)
covers the prose / commit / comment conventions (concise, no emojis,
default-to-no-comments, boundary-only validation, no premature
abstraction).

## License

MIT. See [`LICENSE`](LICENSE).
