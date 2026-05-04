# esphome-studio

Agent-driven ESPHome device design tool. Describe a goal (or pick parts);
get an ESPHome YAML, an ASCII wiring diagram, and a BOM that compile
under upstream ESPHome.

Sister project to [`weirded/distributed-esphome`](https://github.com/weirded/distributed-esphome),
which handles compile + OTA deploy.

## Status

`0.4` (in flight) — Studio web UI with USB device bootstrap. Three-pane
layout (examples sidebar, design preview, inspector). Edit board, fleet,
requirements, warnings, params, and connections; add/remove components
with auto-wiring and auto-bus from the board's defaults. Header
**Connect device** runs esptool-js over WebSerial against a plugged-in
ESP, detects the chip family, and bootstraps a fresh `design.json` with
a matching board pre-filled. See [`web/README.md`](web/README.md) for
UI details and [`START.md`](START.md) for the full roadmap.

## Quickstart

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

### Web UI

```sh
# In one terminal:
python -m studio.api

# In another:
cd web && npm install && npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api/*` to the studio API,
so no CORS plumbing in dev. From the inspector you can edit the board,
fleet metadata, requirements, warnings, per-component params, and
per-connection targets (rail / gpio / bus / expander_pin); the YAML
and ASCII update in real time. Header buttons: **Reset** reverts to
the loaded example; **Download JSON** saves the modified design to disk.

Useful endpoints:

| Method | Path | What it does |
|---|---|---|
| `GET`  | `/library/boards` | summaries of every board in the library |
| `GET`  | `/library/boards/{id}` | full board, including pinout |
| `GET`  | `/library/components?category=&use_case=&bus=` | filtered component summaries |
| `GET`  | `/library/components/{id}` | full component, including ESPHome template |
| `POST` | `/design/validate` | parse a `design.json`, return summary or 422 |
| `POST` | `/design/render` | parse + render a `design.json` to `{yaml, ascii}` |
| `GET`  | `/examples` | list bundled examples |
| `GET`  | `/examples/{id}` | fetch an example as raw `design.json` |

The server is a thin layer over `studio.generate` — same code path the CLI
uses, no server-side state. Permissive CORS for `localhost:5173` /
`localhost:3000` so the 0.3 web UI can hit it during development.

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

Generated artifacts for each are pinned as goldens in
[`tests/golden/`](tests/golden/).

## Architecture

```
   design.json  ── single source of truth (JSON-Schema-validated)
        │
        ▼
  ┌─ studio.model      pydantic models mirroring the schema
  ├─ studio.library    loads boards/ + components/ YAML
  └─ studio.generate   pure functions:
       ├─ yaml_gen     design + library → ESPHome YAML
       └─ ascii_gen    design + library → wiring diagram + BOM
```

Generators are pure functions of `design.json` + the static library — no
artifact-to-document round-trips. Library files in `library/components/`
carry the electrical metadata ESPHome doesn't (pin roles, voltage ranges,
current draw, decoupling caps, pull-up requirements) plus a Jinja2 template
that renders the ESPHome YAML for that component.

## Library

Currently shipped:

**Boards** (`library/boards/`)
- `esp32-devkitc-v4` — ESP32 DevKitC V4 (ESP32-WROOM-32, 4MB flash)
- `nodemcu-32s` — NodeMCU-32S (ESP32-WROOM-32, marks I2S-capable pins)
- `ttgo-lora32-v1` — LilyGO TTGO LoRa32 V1 (ESP32 + onboard SX1276 + onboard SSD1306)
- `wemos-d1-mini` — WeMos D1 Mini (ESP-12F module, ESP8266)
- `nodemcu-v2` — NodeMCU v2 (ESP-12E/F module, ESP8266, breaks out RX/TX/MISO/MOSI as D9-D12)
- `esp01_1m` — ESP-01S 1MB module / Sonoff Basic-class devices

**Components** (`library/components/`)
- `bme280` — Bosch temperature/humidity/pressure sensor (I2C)
- `hc-sr04` — ultrasonic distance sensor (4-pin: VCC, GND, TRIGGER, ECHO)
- `hc-sr501` — PIR motion sensor (used as a generic PIR)
- `ssd1306` — 128×64 OLED (I2C)
- `st7789` — Sitronix ST7789V color TFT (SPI write-only)
- `mcp23008` — 8-bit I2C GPIO expander
- `mcp23017` — 16-bit I2C GPIO expander
- `rc522` — MFRC522 RFID reader (SPI, singleton)
- `sx127x` — Semtech SX1276/SX1278 LoRa radio (SPI, singleton)
- `uart_gps` — generic UART GPS module (NEO-6M / NEO-8M)
- `max98357a` — Maxim Class-D mono I2S amp + DAC
- `ws2812b` — addressable RGB LED (NeoPixel/neopixelbus)
- `gpio_input` — generic binary_sensor on a GPIO or expander pin (buttons, limit switches, door/window/motion sensors)
- `gpio_output` — generic switch on a GPIO or expander pin (relays, indicators)

The `gpio_input` / `gpio_output` components and the `kind: expander_pin`
connection target together let downstream platforms hang off any expander
without bloating `esphome_extras`. See `examples/securitypanel.json` for a
12-sensor MCP23017 wiring or `examples/awning-control.json` for a mix of
expander inputs and outputs.

The library is intentionally small. It will grow as we convert more
device configs from the corpus in `moellere/esphome`. See
[`START.md` § Library sourcing strategy](START.md#library-sourcing-strategy)
for the hybrid plan.

## Layout

```
schema/                   JSON Schema for design.json (source of truth)
library/boards/           board manifests (pinout, rails, framework)
library/components/       component manifests (electrical + ESPHome template)
studio/                   python: model, library loader, generators, CLI
examples/                 sample design.json files
tests/                    pytest suite + golden artifacts
START.md                  vision, decisions, phase plan
CLAUDE.md                 working conventions for both Claude and humans
```

## Tests

```sh
python -m pytest          # full suite
python -m ruff check .    # lint
```

Golden tests pin the generator output for every example. Regenerate goldens
with the CLI when output legitimately changes; commit the new files in the
same diff as the code change.

## Roadmap (compressed)

- **0.1** ✅ pipeline + library scaffolding
- **0.2** ✅ HTTP API (FastAPI) — same generators, exposed over JSON
- **0.3** ✅ Studio web UI v1 — three-pane shell + form-based editing
- **0.4** 🚧 USB device bootstrap (WebSerial + esptool-js)
- **0.4** USB device bootstrap via WebSerial / esptool-js
- **0.5** Agent layer (Claude tool-using, in the UI sidebar)
- **0.6** CSP solver — pin/bus/budget assignment + ranked recommendations
- **0.7** distributed-esphome handoff — push device + YAML to ha-addon
- **0.8** Enclosure suggestions
- **Future** KiCad schematic + PCB layout

Full plan with decisions, schemas, and per-phase scope lives in
[`START.md`](START.md).

## Contributing

See [`CLAUDE.md`](CLAUDE.md) for working conventions (concise prose, no
emojis in code/commits, no premature abstraction, default-to-no-comments,
boundary-only validation).

## License

MIT. See [`LICENSE`](LICENSE).
