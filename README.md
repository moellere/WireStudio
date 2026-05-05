# esphome-studio

Agent-driven ESPHome device design tool. Describe a goal (or pick parts);
get an ESPHome YAML, an ASCII wiring diagram, and a BOM that compile
under upstream ESPHome.

Sister project to [`weirded/distributed-esphome`](https://github.com/weirded/distributed-esphome),
which handles compile + OTA deploy.

## Status

`v0.9.0` — first tagged release. End-to-end pipeline from
`design.json` through ESPHome YAML + fleet push + parametric
enclosure + KiCad schematic. Ships as a single Docker image you can
self-host (`ghcr.io/moellere/esphome-studio`). Three-pane web UI
covers manual editing; a Claude tool-using agent drives the design
via natural language; a CSP solver auto-assigns pins; a port-
compatibility checker catches boot-strap, ADC2/WiFi, voltage, and
locked-pin issues before YAML render.

See [`CHANGELOG.md`](CHANGELOG.md) for the long form per release and
[`START.md`](START.md) for design notes / future scope.

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
  -v studio-data:/data \
  ghcr.io/moellere/esphome-studio:v0.9.0
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
python -m studio.generate examples/garage-motion.json
```

Prints rendered YAML and the ASCII wiring block to stdout. To write to files:

```sh
python -m studio.generate examples/garage-motion.json \
    --out-yaml build/garage-motion.yaml \
    --out-ascii build/garage-motion.txt
```

### HTTP API

```sh
python -m studio.api                    # localhost:8765
python -m studio.api --reload           # dev mode (auto-reload on edits)
```

Browse the auto-generated OpenAPI docs at <http://127.0.0.1:8765/docs>.

To enable the **agent** endpoints (`/agent/turn`, `/agent/sessions/{id}`),
export an Anthropic API key before starting the server:

```sh
export ANTHROPIC_API_KEY=sk-ant-...
python -m studio.api
```

Without a key, `/agent/status` reports `available: false` and the agent
sidebar in the UI shows a friendly notice instead of trying to talk.

To enable the **fleet handoff** (`/fleet/push` and the **Push to fleet**
header button), point the API at a running distributed-esphome ha-addon:

```sh
export FLEET_URL=http://homeassistant.local:8765
export FLEET_TOKEN=$(grep -oP '(?<=token: )\S+' .../addon/secrets.yaml)
python -m studio.api
```

`GET /fleet/status` reports `available: true` when both env vars are set
and the addon answers a probe; otherwise the UI surfaces the specific
reason (URL missing, unauthorized, unreachable).

### Web UI (dev)

```sh
# In one terminal:
python -m studio.api

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
(`studio.generate`, `studio.csp`, `studio.recommend`, `studio.fleet`,
`studio.enclosure`, `studio.kicad`). Server state is limited to the
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
| [`esp32-audio.json`](examples/esp32-audio.json) | NodeMCU-32S | I2S audio (MAX98357A DAC) + ST7789V SPI dashboard display, ESP-IDF framework |
| [`bluesonoff.json`](examples/bluesonoff.json) | ESP-01S 1MB | Sonoff Basic relay; front button (boot strap pin) toggles a single GPIO relay |
| [`wemosgps.json`](examples/wemosgps.json) | WeMos D1 Mini | UART GPS module — lat/lon/altitude/speed/satellites + runtime baud-rate selector |
| [`ttgo-lora32.json`](examples/ttgo-lora32.json) | TTGO LoRa32 V1 | ESP32 + onboard SX1276 LoRa radio + onboard SSD1306 OLED + battery ADC, ESP-IDF |
| [`multi-temp.json`](examples/multi-temp.json) | WeMos D1 Mini | Two DS18B20 temp sensors sharing a single 1-wire bus + an RCWL-0516 microwave motion sensor |

Generated artifacts for each are pinned as goldens in
[`tests/golden/`](tests/golden/).

## Architecture

```
   design.json  ── single source of truth (JSON-Schema-validated)
        │
        ▼
  ┌─ studio.model         pydantic models mirroring the schema
  ├─ studio.library       loads boards/ + components/ YAML
  ├─ studio.generate      design + library → ESPHome YAML + ASCII
  ├─ studio.csp           pin solver + port-compatibility checker
  ├─ studio.recommend     deterministic capability ranking
  ├─ studio.agent         Claude tool-using agent + session store
  ├─ studio.designs       file-backed designs/<id>.json store
  ├─ studio.fleet         distributed-esphome HTTP client
  ├─ studio.enclosure     parametric OpenSCAD + Thingiverse search
  ├─ studio.kicad         SKiDL Python script emitter
  └─ studio.api           FastAPI HTTP layer (mounts everything above)
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

**Components** (`library/components/`)

_Environmental sensors:_
- `bme280` — Bosch temperature/humidity/pressure sensor (I2C)
- `bmp180` — Bosch BMP180/BMP085 barometric pressure + temperature (I2C)
- `bmp280` — Bosch temperature/pressure sensor (I2C, no humidity)
- `dht` — DHT11 / DHT22 / AM2302 temperature + humidity (single-wire)
- `htu21d` — TE Connectivity HTU21D temperature + humidity (I2C; covers Si7021 / SHT2x)
- `ds18b20` — Dallas DS18B20 1-Wire temperature sensor (single-pin bus + 4.7kΩ pull-up)

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
- `mcp23008` — 8-bit I2C GPIO expander
- `mcp23017` — 16-bit I2C GPIO expander
- `ads1115` — TI 4-channel 16-bit ADC (I2C) hub; rescues ESP32 designs from the ADC2/WiFi conflict
- `ads1115_channel` — one logical reading on an ADS1115 hub (multiplexer + gain + update_interval per channel)

_Generic IO:_
- `gpio_input` — generic binary_sensor on a GPIO or expander pin (buttons, limit switches, door/window/motion sensors)
- `gpio_output` — generic switch on a GPIO or expander pin (relays, indicators)
- `adc` — generic analog input (battery monitoring, potentiometers, LDRs)
- `pulse_counter` — pulse counter / tachometer (RPM, flow, energy meters)

_Light / audio / camera:_
- `ws2812b` — WS2812B / SK6812 addressable RGB LED (1-wire NeoPixel)
- `apa102` — APA102 / SK9822 addressable RGB strip (DotStar, SPI-style)
- `max98357a` — Maxim Class-D mono I2S amp + DAC
- `rtttl` — piezo buzzer + RTTTL melody player (PWM output)
- `esp32_camera` — ESP32 OV2640 / OV7670 / OV5640 camera

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
studio/                  python package — see Architecture above for the module map
web/                     React 19 + Vite + Tailwind v4 SPA
examples/                bundled design.json files (every one pinned by goldens)
tests/                   pytest + golden artifacts; vitest tests under web/src
deploy/                  k8s.yaml, docker-compose.yml, nginx.conf for self-hosting
Dockerfile               multi-stage build for the published GHCR image
.github/workflows/       GHA workflow that publishes ghcr.io/.../esphome-studio
CHANGELOG.md             per-release feature deltas
START.md                 vision, decisions, phase plan
CLAUDE.md                working conventions for both Claude and humans
```

## Tests

```sh
python -m pytest          # ~297 cases, ~10s
python -m ruff check .    # lint
cd web && npx vitest run  # ~125 cases, ~5s (vitest + jsdom)
```

Golden tests pin the generator output for every bundled example.
Regenerate goldens with the CLI when output legitimately changes;
commit the new files in the same diff as the code change. The web
suite covers `lib/design.ts` plus React components (BusList,
ConnectionForm, EnclosureDialog, Inspector, CapabilityPickerDialog,
PinoutView, PushToFleetDialog, SchematicDialog) via React Testing
Library + jsdom; network surfaces are mocked at the api/client
boundary so the suite stays offline.

The GitHub Actions workflow runs the full suite + multi-arch image
build on every PR + merge to main.

## Roadmap (compressed)

- **0.1** ✅ pipeline + library scaffolding
- **0.2** ✅ HTTP API (FastAPI) — same generators, exposed over JSON
- **0.3** ✅ Studio web UI v1 — three-pane shell + form-based editing
- **0.4** ✅ USB device bootstrap (WebSerial + esptool-js)
- **0.5** ✅ Agent layer (Claude tool-using; sessions in `sessions/<id>.jsonl`)
- **0.5+** ✅ streaming agent responses + recommendation mode
- **0.6** ✅ CSP solver — auto-assign unbound pins, detect conflicts + budget overruns; port-compatibility validation (boot straps, serial pins, input-only, A0 voltage cap, ADC2/WiFi conflict, locked-pin invariants)
- **0.6+** ✅ server-side design persistence + **New design** dialog, capability-driven **Add by function** picker, pin-lock UI, bus editor (rename propagation + inline compat), drag-and-drop pinout, strict-mode toggle
- **0.7** ✅ distributed-esphome handoff — push device + YAML to ha-addon, optional compile, build-log polling + SSE streaming, strict-only push gate
- **0.8** ✅ Enclosure suggestions — parametric OpenSCAD generator + Thingiverse search relay
- **0.9** ✅ KiCad schematic export — SKiDL Python emitter; 100% library `kicad:` mapping
- **Deployment** ✅ Docker single-image (multi-arch GHCR) + Kubernetes manifest + nginx compose recipe
- **1.0** KiCad PCB layout — Freerouting + Gerber + JLCPCB CPL/BOM export
- **Future** multi-writer state backend (HA replicas)

Full plan with decisions, schemas, and per-phase scope lives in
[`START.md`](START.md). Per-release feature deltas live in
[`CHANGELOG.md`](CHANGELOG.md).

## Contributing

See [`CLAUDE.md`](CLAUDE.md) for working conventions (concise prose, no
emojis in code/commits, no premature abstraction, default-to-no-comments,
boundary-only validation).

## License

MIT. See [`LICENSE`](LICENSE).
