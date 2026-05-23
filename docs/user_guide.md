# User guide

[← docs index](index.md)

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

For driving the studio over MCP, the fleet handoff, and enclosure
search, see [Integrations](integrations.md).

## Web UI

Run the dev server (see [the README quickstart](../README.md#quickstart)),
open <http://localhost:5173>. The same UI is served at `/` from the
production Docker image.

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

## HTTP API endpoints

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
| `GET`  | `/fleet/status` | check whether `FLEET_URL` + `FLEET_TOKEN` reach a fleet-for-esphome ha-addon |
| `POST` | `/fleet/push` | render `design.json` and push it as `<device_name>.yaml` (optionally `compile: true`) |
| `GET`  | `/fleet/jobs/{run_id}` | aggregated compile verdict for a Push-to-fleet run |
| `GET`  | `/fleet/jobs/{run_id}/log?offset=N` | poll the addon's build log for a compile run; returns `{log, offset, finished}` |
| `GET`  | `/fleet/jobs/{run_id}/log/stream` | Server-Sent Events relay over the same log endpoint; ~300ms cadence, exits with `event: done` when the build finishes |

The HTTP API is a thin layer over the studio's pure-function modules
(`wirestudio.generate`, `wirestudio.csp`, `wirestudio.recommend`, `wirestudio.fleet`,
`wirestudio.enclosure`, `wirestudio.kicad`). Server state is limited to the
agent session log + the saved-design store — both file-backed under
`/data` (via `SESSIONS_DIR` / `DESIGNS_DIR`). Permissive CORS for
`localhost:5173` / `localhost:3000` so the dev Vite server can hit
it without a proxy. Browse the auto-generated OpenAPI docs at
<http://127.0.0.1:8765/docs>.

## Examples

| Example | Board | What it is |
|---|---|---|
| [`garage-motion.json`](../wirestudio/examples/garage-motion.json) | ESP32-DevKitC-V4 | PIR + BME280 (temp/humidity/pressure) over I2C |
| [`awning-control.json`](../wirestudio/examples/awning-control.json) | WeMos D1 Mini | Cover controller — 4 limit switches + buttons via MCP23008 expander, 2 GPIO relays, dual-PWM motor drive |
| [`wasserpir.json`](../wirestudio/examples/wasserpir.json) | WeMos D1 Mini | Single PIR with a scheduled nightly reboot |
| [`oled.json`](../wirestudio/examples/oled.json) | WeMos D1 Mini | SSD1306 status display rendering time, date, IP |
| [`bluemotion.json`](../wirestudio/examples/bluemotion.json) | WeMos D1 Mini | PIR + WS2812B NeoPixel; motion lights the LED |
| [`distance-sensor.json`](../wirestudio/examples/distance-sensor.json) | NodeMCU v2 | HC-SR04 ultrasonic + WS2812B NeoPixel; LED color tracks distance |
| [`securitypanel.json`](../wirestudio/examples/securitypanel.json) | WeMos D1 Mini | 12 door/window/motion sensors via MCP23017 expander, RTTTL piezo, GPIO siren |
| [`rc522.json`](../wirestudio/examples/rc522.json) | WeMos D1 Mini | MFRC522 RFID reader (SPI), NeoPixel status LED, RTTTL piezo, manual button |
| [`esp32-audio.json`](../wirestudio/examples/esp32-audio.json) | NodeMCU-32S | I2S audio (MAX98357A DAC) + ST7789V SPI dashboard display, Arduino framework |
| [`bluesonoff.json`](../wirestudio/examples/bluesonoff.json) | ESP-01S 1MB | Sonoff Basic relay; front button (boot strap pin) toggles a single GPIO relay |
| [`wemosgps.json`](../wirestudio/examples/wemosgps.json) | WeMos D1 Mini | UART GPS module — lat/lon/altitude/speed/satellites + runtime baud-rate selector |
| [`ttgo-lora32.json`](../wirestudio/examples/ttgo-lora32.json) | TTGO LoRa32 V1 | ESP32 + onboard SX1276 LoRa radio + onboard SSD1306 OLED + battery ADC, ESP-IDF |
| [`multi-temp.json`](../wirestudio/examples/multi-temp.json) | WeMos D1 Mini | Two DS18B20 temp sensors sharing a single 1-wire bus + an RCWL-0516 microwave motion sensor |
| [`room-climate.json`](../wirestudio/examples/room-climate.json) | WeMos D1 Mini | BH1750 ambient-light + AHT20 temp/humidity on one I2C bus |
| [`desk-climate.json`](../wirestudio/examples/desk-climate.json) | ESP32-C3-DevKitM-1 | Sensirion SHT3x precision temp/humidity over I2C |
| [`parking-distance.json`](../wirestudio/examples/parking-distance.json) | NodeMCU v2 | VL53L0X laser ToF distance (indoor parking-spot indicator) |
| [`keypad.json`](../wirestudio/examples/keypad.json) | WeMos D1 Mini | 8 buttons read through a PCF8574 GPIO expander over I2C |
| [`smart-plug.json`](../wirestudio/examples/smart-plug.json) | ESP8285 1MB | Athom-style smart plug — relay + button + CSE7766 AC power metering over UART 4800 8E1 |
| [`smart-plug-v1.json`](../wirestudio/examples/smart-plug-v1.json) | ESP8285 1MB | Older Athom v1 / Sonoff POW R1 plug — same topology with the HLW8012 / BL0937 3-pin pulse meter |
| [`desk-matrix.json`](../wirestudio/examples/desk-matrix.json) | ESP32-DevKitC | 8x8 WS2812 matrix driven by the ESP32 RMT peripheral (no bit-banging) |
| [`rs485-energy.json`](../wirestudio/examples/rs485-energy.json) | ESP32-DevKitC-V4 | Eastron SDM230 single-phase energy meter via Modbus RTU (UART2 + MAX485 transceiver, GPIO5 drives DE+RE) |
| [`bl0906-mainmeter.json`](../wirestudio/examples/bl0906-mainmeter.json) | ESP32-DevKitC-V4 | BL0906 6-channel CT-clamp energy monitor over UART2 (Athom EM6-style whole-home sub-metering) |
| [`nextion-thermostat.json`](../wirestudio/examples/nextion-thermostat.json) | ESP32-DevKitC-V4 | Nextion HMI thermostat panel — display on UART2 + SHT3xD temp/humidity on default I2C |
| [`tuya-smart-plug.json`](../wirestudio/examples/tuya-smart-plug.json) | ESP8285 1MB | Tuya-MCU smart plug — relay (DP 1) + power (DP 17) + energy (DP 18) over UART 9600; logger off UART0 |
| [`weather-station.json`](../wirestudio/examples/weather-station.json) | ESP32-DevKitC-V4 | BMP280 barometer + HTU21D temp/humidity + TSL2561 lux on one shared I2C bus |
| [`attic-logger.json`](../wirestudio/examples/attic-logger.json) | WeMos D1 Mini | DHT22 single-wire temp/humidity + legacy BMP180 I2C barometer |
| [`atom-echo.json`](../wirestudio/examples/atom-echo.json) | M5Stack Atom Echo | Onboard SK6812 RGB LED (RMT-driven) + the programmable front button |
| [`atom-matrix.json`](../wirestudio/examples/atom-matrix.json) | M5Stack Atom Matrix | Onboard 5x5 (25-LED) SK6812 RGB matrix + the programmable button |
| [`atomu.json`](../wirestudio/examples/atomu.json) | M5Stack AtomU | USB-A stick — onboard SK6812 RGB LED + button |
| [`atoms3-lite.json`](../wirestudio/examples/atoms3-lite.json) | M5Stack AtomS3 Lite | ESP32-S3 — onboard WS2812C RGB LED + button |
| [`oled-knob.json`](../wirestudio/examples/oled-knob.json) | ESP32-DevKitC-V4 | 1.3" SH1106 OLED + EC11 rotary-encoder combo module — display on I2C, encoder A/B + push button on GPIO |
| [`analog-node.json`](../wirestudio/examples/analog-node.json) | ESP32-DevKitC-V4 | ADS1115 I2C ADC with two channels (single-ended + differential) plus an onboard ADC1 pin |
| [`kitchen-scale.json`](../wirestudio/examples/kitchen-scale.json) | WeMos D1 Mini | HX711 load-cell ADC + SSD1306 OLED readout in grams |
| [`grill-probe.json`](../wirestudio/examples/grill-probe.json) | ESP32-DevKitC-V4 | MAX31855 K-type thermocouple over read-only SPI + MPU6050 IMU as lid sensor |
| [`atoms3-lcd.json`](../wirestudio/examples/atoms3-lcd.json) | M5Stack AtomS3 | 20x4 HD44780 character LCD over the Grove I2C port via a PCF8574 backpack |
| [`atoms3-onboard.json`](../wirestudio/examples/atoms3-onboard.json) | M5Stack AtomS3 | The board's built-in parts auto-populated: onboard ST7789 LCD (SPI) + MPU6886 IMU (I2C) + front button |

Generated artifacts for each are pinned as goldens in
[`tests/golden/`](../tests/golden/). For a per-component / per-board view of
which library entries are exercised by these examples, see
[library-coverage.md](library-coverage.md) (regenerate with
`python scripts/coverage_matrix.py`).
