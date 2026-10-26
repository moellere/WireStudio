# User guide

[← docs index](index.md)

## What it does

- **Design.** Web UI inspector (board, fleet metadata, components,
  buses, connections, requirements, warnings). Add components by
  picking a capability (**Add by function**) — the recommender ranks
  library matches against use cases. Drag-and-drop pinout for
  component-to-board pin assignment. Pin locks per role. Bus editor
  with rename propagation + inline compatibility warnings. USB
  bootstrap from a plugged-in ESP via WebSerial + esptool-js — the
  detected chip is matched to a board family, and the board's built-in
  peripherals (LCD, button, IMU, RGB/IR, LoRa, GPS, ...) are
  auto-populated and wired. Saved designs at `designs/<id>.json` with a
  **Saved** tab + **New design** dialog (which seeds onboard parts too).
- **Validate.** CSP pin solver assigns every unbound connection with
  capability-aware fallback (boot strap pins de-prioritised; ADC1
  preferred over ADC2 on classic ESP32). Port-compatibility checker
  flags input-only-as-output errors, boot-strap risks, serial console
  reuse, voltage limits, ADC2/WiFi conflicts, locked-pin mismatches.
  Strict mode (header toggle) promotes warn/error compat to render
  errors as a pre-deploy gate.
- **Generate.** Pure functions over `design.json` + the static
  library produce ESPHome YAML, ASCII wiring diagrams + BOM and a
  parametric OpenSCAD enclosure (`.scad`). The same design renders for
  the other frameworks: a Tasmota device template, WLED's `cfg.json`
  (plus a `platformio_override.ini` when a part is a usermod), a
  CircuitPython `code.py`, a MicroPython `main.py` and the standalone
  LoRaWAN firmware. **Schematic** (advanced mode) previews and
  downloads a KiCad 8 `.kicad_sch` the studio draws itself, exports a
  placed `.kicad_pcb`, routes it with Freerouting, and builds the
  JLCPCB bundle (BOM, CPL, Gerber + drill). Bundled examples are
  pinned as goldens.
- **Parts.** A component can be a subcircuit of discrete parts; the
  inspector shows what it expands into and the part values follow the
  instance's params. **Inventory** (header button) cross-references the BOM
  against what is on hand (library modules plus a drawer of discrete
  parts, imported from a spreadsheet), proposes same-package
  substitutes ranked by pinout, package, rating headroom and stock,
  applies one with *Use for ...* or every best proposal with *Use all
  suggested substitutes*, and ends in a pick list by drawer location
  and a buy list priced on JLCPCB.
- **Author components.** **New component** and a user component's
  *Edit YAML* open an editor whose *Check* runs the same gate the
  bundled library passes: schema, subcircuit nets, the ESPHome template
  render and the KiCad symbol, pins and footprint. A component that
  passes lands in the user library (`LIBRARY_USER_DIR`) and is
  available to every design; `component_create` does the same over
  MCP.
- **Author boards.** **New board** in the Boards tab, and *Copy as new*
  or *Edit YAML* on a board, open the same editor on a board's YAML. Its
  *Check* runs the board gate: every bus, onboard-peripheral and radio
  pin against the GPIO list, the KiCad symbol's pins, the enclosure's
  geometry, and an ESPHome render with the onboard parts. A board that
  passes lands in the user library and is offered for new designs;
  `board_create` does the same over MCP.
- **Flash.** One flash dialog (**Flash firmware**, radio icon) covers
  six frameworks over the same WebSerial + esptool-js mechanism:
  **ESPHome** hands off to a fleet push or an ESPHome dashboard
  compile (OTA, no serial flash),
  **Tasmota** fetches the official release image for the design's chip
  and offers a post-flash template + WiFi push over serial,
  **LoRaWAN** compiles and flashes the RadioLib firmware,
  **Meshtastic** flashes the official factory image for the mapped
  radio boards and then pushes region, modem preset, owner and the
  primary channel (with a generated or pasted key) over the same serial
  port, and
  **CircuitPython** flashes the official release image and serves a
  generated starter `code.py` (save-to-CIRCUITPY or download), and
  **MicroPython** flashes the official port image for the board's chip
  and pushes a `main.py` generated from the design over the same serial
  port through the raw REPL (or against any connected board).
- **Build ESPHome firmware.** Two paths, both under **Push to fleet**
  (advanced mode): the
  [fleet-for-esphome](integrations.md) add-on (`FLEET_URL` +
  `FLEET_TOKEN`), or any ESPHome Device Builder, the Home Assistant add-on
  or a standalone one (`ESPHOME_DASHBOARD_URL`). Either
  writes the rendered YAML as `<device_name>.yaml`, optionally starts a
  compile, and streams the build log; the dashboard path also serves
  the firmware image. The dialog offers whichever backend is
  configured.
- **Workbench.** With `WORKBENCH_URL` (and `WORKBENCH_TOKEN`) pointing
  at a [workbench](workbench.md) bench, the flash dialog's target
  picker adds **Workbench slot** next to local USB: the image is
  flashed on a board at the bench, the slot's serial output is relayed
  back, and a boot verdict reads the framework's start-up marker
  (`/workbench/verify-boot`). Over MCP, `lorawan_workbench_provision`
  runs the whole LoRaWAN bring-up (flash, register in ChirpStack, key
  push, join) against a slot with no one at the bench. The picker
  stays hidden when no bench is configured.
- **LoRaWAN (radio boards).** Two flows for US915 radio boards (TTGO
  LoRa32 / T-Beam, Heltec WiFi LoRa 32 V2 / V3 / V4):
  - **Flash LoRaWAN firmware** (radio icon, advanced mode) builds the
    standalone RadioLib + LoRaWAN_ESP32 path and flashes over WebSerial
    with runtime serial provisioning. Hardware-validated.
  - **Provision LoRaWAN device** (key icon) drives the
    `lorawan-for-esphome` external-component path: detect the chip's
    eFuse MAC, mint keys against ChirpStack, push to fleet with the
    secrets inlined, watch the OTAA join land. The device joins the
    same ESPHome / fleet-for-esphome compile path as every other
    design.
  See [Integrations](integrations.md#lorawan--chirpstack).

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

The header groups its buttons by phase. **Design**: New, Save,
Share, Reset. **Parts**: Add by function (capability picker), Inventory,
Connect device (USB bootstrap). **Check**: Solve pins and the **strict**
toggle. **Output**: Flash firmware, Push to fleet, Provision LoRaWAN
device, Schematic (KiCad export), Enclosure (parametric `.scad` +
Thingiverse search) and Export (design JSON). Then Agent (chat sidebar),
feedback, theme, **Settings** (gear) and the API docs. Advanced mode,
switched in Settings, reveals the Agent, the schematic and PCB tabs, and
every Output button but Export. Below 1800px wide the group names and
the longer labels hide, and below 1366px the Design labels too; hover a
button for its name.

**Community designs.** The sidebar's **Gallery** tab lists the
designs in the community catalogue,
[`moellere/wirestudio-designs`](https://github.com/moellere/wirestudio-designs).
You can filter by name, author, board, tag or part. Picking a design
opens it like an example, installing any components its author wrote
into your user library first (never over one of yours with the same
id). A design that runs code the studio did not generate -- a lambda,
external components -- carries a **custom code** badge: read it before
you flash. The design keeps an `origin` block naming
the catalogue entry and its author, because catalogue designs are
CC-BY-4.0 and the credit has to survive your edits.

**Share** packs the open design as a folder (`design.json`,
`meta.yaml`, a README from your notes, and up to four photos of the
build, and the components you wrote that it uses), downloads it as a
zip and opens the catalogue's upload page.
Each photo is shrunk to 2048 px and re-encoded as JPEG with all its
metadata removed, including any GPS location a phone recorded. The
Gallery shows a design's first photo once it has merged; photos in an
open pull request never reach the studio. Unzip it, drag the folder in and
open the pull request GitHub offers. CI checks the design and the
owner reviews it. A design imported from the catalogue is shared with
`derived_from` set. Sharing refuses a design holding a literal Wi-Fi,
API or LoRaWAN key. `WIRESTUDIO_DESIGNS_REPO` points both at a fork,
or turns them off.

**Community library.** The catalogue also holds components and boards on
their own, MIT-licensed so they can be promoted into the bundled library.
The Components and Boards tabs list the ones you do not have under
**From the community**, with their author. **Install** runs the same gate
as the editor before saving into your user library, and never replaces
an entry of yours with the same id. A user component or board you wrote
has **Share** on its inspector card: it packs the YAML, a `meta.yaml`
with your handle, tags and the datasheet you worked from, and a README
from your notes, and opens the catalogue's library upload page. A design
on a board you wrote shares and imports with that board, as it does with
your components.

The **Settings** dialog surfaces the MCP bearer token: reveal, copy, or
regenerate it without leaving the browser (read-only when the token is
pinned via `WIRESTUDIO_MCP_TOKEN`). See [the MCP guide](mcp.md#auth).

## HTTP API endpoints

| Method | Path | What it does |
|---|---|---|
| `GET`  | `/library/boards` | summaries of every board in the library |
| `GET`  | `/library/boards/{id}` | full board, including pinout |
| `POST` | `/library/boards/check` · `/library/boards` | run the board gate on a YAML draft; save it into the user library (201, 409 on a clash, 422 on a failed check) |
| `GET` / `DELETE` | `/library/boards/{id}/yaml` · `/library/boards/{id}` | a board's YAML source; remove a user board |
| `GET`  | `/library/components?category=&use_case=&bus=` | filtered component summaries |
| `GET`  | `/library/components/{id}` | full component, including ESPHome template |
| `GET`  | `/library/use_cases` | distinct capabilities across the library, with counts; powers the **Add by function** picker |
| `POST` | `/library/recommend` | rank library components against a free-text or capability query |
| `POST` | `/design/validate` | parse a `design.json`, return summary or 422 |
| `POST` | `/design/render` | parse + render a `design.json` to `{yaml, ascii}` |
| `POST` | `/design/enclosure/openscad` | generate a parametric `.scad` shell for the design's board |
| `POST` | `/design/kicad/sch` | the design as a KiCad 8 `.kicad_sch`, drawn by the studio with symbols embedded (`/design/kicad/sch/status` gates it on the symbol libraries) |
| `POST` | `/design/kicad/schematic` | generate a SKiDL Python script the user runs locally to produce a `.kicad_sch` |
| `POST` | `/design/kicad/erc` | run `kicad-cli sch erc` on the generated schematic; violations with per-type counts (`/design/kicad/erc/status` gates it on the symbol libraries + kicad-cli) |
| `GET`  | `/enclosure/search?library_id=...&query=...` | search community-uploaded enclosure models (Thingiverse) |
| `GET`  | `/enclosure/search/status` | per-source availability + configure hints |
| `GET`  | `/examples` | list bundled examples |
| `GET`  | `/examples/{id}` | fetch an example as raw `design.json` |
| `GET`  | `/community/status` | whether the community catalogue is on, and its repo, upload and contribution URLs |
| `GET`  | `/community/designs` | the catalogue's index: slug, name, author, tags, board, components per design |
| `POST` | `/community/designs/{slug}/import` | one catalogue design, migrated, with `origin` set for attribution; installs the user components and board it ships (409 if yours differs) |
| `POST` | `/community/share` | `{design, author, tags, notes?, photos?: [{name, data}]}`: the design as a zip folder for the catalogue's upload page, photos (base64, up to 4) re-encoded without metadata; 422 on a literal credential or an unreadable photo |
| `GET`  | `/community/library` | the catalogue's components and boards, each with `installed` (`bundled`, `user` or empty) |
| `POST` | `/community/library/{components\|boards}/{id}/install` | install one through its gate; nothing to do when the same text is here, 409 when a different one is |
| `POST` | `/community/library/share` | `{kind, id, author, tags, source?, notes?}`: a user component or board as the zip folder the catalogue's `library/` expects; 422 unless it is yours and still passes its gate |
| `GET`  | `/fleet/status` | check whether `FLEET_URL` + `FLEET_TOKEN` reach a fleet-for-esphome ha-addon |
| `POST` | `/fleet/push` | render `design.json` and push it as `<device_name>.yaml` (optionally `compile: true`) |
| `GET`  | `/fleet/jobs/{run_id}` | aggregated compile verdict for a Push-to-fleet run |
| `GET`  | `/fleet/jobs/{run_id}/log?offset=N` | poll the addon's build log for a compile run; returns `{log, offset, finished}` |
| `GET`  | `/fleet/jobs/{run_id}/log/stream` | Server-Sent Events relay over the same log endpoint; ~300ms cadence, exits with `event: done` when the build finishes |
| `GET`  | `/esphome/status` | check whether `ESPHOME_DASHBOARD_URL` reaches an ESPHome Device Builder |
| `POST` | `/esphome/push` | render `design.json`, write it to the dashboard as `<device_name>.yaml`, optionally start a compile there |
| `GET`  | `/esphome/jobs/{run_id}` · `/log` · `/log/stream` · `/firmware` | verdict, incremental log, SSE relay and firmware download for a dashboard compile, the same shapes as the fleet routes |
| `GET`  | `/workbench/slots/{slot}/output?since=` | lines the bench's recorder captured on a slot after an epoch; the flash dialog relays them after a slot flash |
| `POST` | `/workbench/verify-boot` | `{slot, framework, since?, reset?}`: did the firmware boot? Searches the recorder from `since`, then watches for the framework's marker. `reset` restarts the board through the bench first and searches from there, which a check straight after a flash needs |
| `POST` | `/tasmota/template` | emit a Tasmota device template (solved pins → GPIO function ids) |
| `GET`  | `/tasmota/firmware?chip=` | proxy the official Tasmota release image for the chip (`/tasmota/firmware/status` gates it) |
| `GET`  | `/meshtastic/firmware?board=` | proxy the official Meshtastic factory image for a mapped radio board (`/meshtastic/firmware/status` gates it) |
| `GET`  | `/circuitpython/firmware?board=` | proxy the official CircuitPython release image for an ESP32-family board (`/circuitpython/firmware/status` gates it, and flags generic-image fallbacks) |
| `GET`  | `/circuitpython/code?board=` | starter `code.py` generated from the board's library metadata |
| `GET`  | `/micropython/firmware?board=` | proxy the newest stable micropython.org image for the board's chip (`/micropython/firmware/status` lists the image and flash offset per board); `X-Flash-Offset` is 0x1000 on the classic ESP32 |
| `GET`/`POST` | `/micropython/code` | `?board=` serves a starter `main.py`; a posted `design.json` returns `{code, deps, warnings}` with `deps` as `mip` package specs |

The table above is a working subset — schematic/PCB/fab/route, LoRaWAN,
designs, seed, inventory, and agent endpoints are all in the
auto-generated OpenAPI docs, which are authoritative.

The HTTP API is a thin layer over the studio's pure-function modules
(`wirestudio.generate`, `wirestudio.csp`, `wirestudio.recommend`, `wirestudio.fleet`,
`wirestudio.enclosure`, `wirestudio.kicad`). Server state is limited to the
agent session log and the saved-design store (file-backed under
`/data` via `SESSIONS_DIR` / `DESIGNS_DIR`, or one SQLite file each via
`SESSIONS_DB` / `DESIGNS_DB`), the inventory (`INVENTORY_PATH`) and the
user component library (`LIBRARY_USER_DIR`). Permissive CORS for
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
| [`atomu-onboard.json`](../wirestudio/examples/atomu-onboard.json) | M5Stack AtomU | Onboard set: SK6812 RGB LED + button + IR transmitter + SPM1423 PDM microphone |
| [`atom-lite.json`](../wirestudio/examples/atom-lite.json) | M5Stack Atom Lite | Onboard SK6812 RGB LED + button + I2S microphone |
| [`t-beam.json`](../wirestudio/examples/t-beam.json) | LilyGO TTGO T-Beam | Onboard SX1276 LoRa radio + NEO-6M GPS (dedicated UART) + user button |
| [`s3-devkitc.json`](../wirestudio/examples/s3-devkitc.json) | ESP32-S3-DevKitC-1 | Onboard WS2812 RGB LED + BOOT button |
| [`s3-supermini.json`](../wirestudio/examples/s3-supermini.json) | ESP32-S3 SuperMini | Onboard WS2812 RGB LED + BOOT button |
| [`c6-supermini.json`](../wirestudio/examples/c6-supermini.json) | ESP32-C6 SuperMini | Onboard WS2812 RGB LED + BOOT button |
| [`c3-supermini.json`](../wirestudio/examples/c3-supermini.json) | ESP32-C3 SuperMini | Onboard plain status LED + BOOT button |
| [`tft-touch.json`](../wirestudio/examples/tft-touch.json) | ESP32-DevKitC-V4 | ILI9341 SPI TFT + XPT2046 resistive touch on a shared SPI bus |
| [`led-display.json`](../wirestudio/examples/led-display.json) | ESP32-DevKitC-V4 | MAX7219 8x8 LED matrix (SPI) + TM1638 LED&KEY 7-seg module |
| [`esp32cam.json`](../wirestudio/examples/esp32cam.json) | AI-Thinker ESP32-CAM | OV2640 camera over the fixed DVP pinout + camera web server |
| [`esp32cam-wrover.json`](../wirestudio/examples/esp32cam-wrover.json) | ESP32-WROVER-CAM | OV2640 on the Freenove WROVER pinout (XCLK GPIO32, SCCB on GPIO13/12) |
| [`subghz-rfid.json`](../wirestudio/examples/subghz-rfid.json) | ESP32-DevKitC-V4 | CC1101 433MHz transceiver (SPI) + RDM6300 125kHz RFID reader (UART) |
| [`presence-rf.json`](../wirestudio/examples/presence-rf.json) | ESP32-DevKitC-V4 | LD2420 24GHz mmWave presence (UART) + Sonoff-style 433MHz RF bridge (UART) |
| [`flow-meter.json`](../wirestudio/examples/flow-meter.json) | ESP32-DevKitC-V4 | Pulse-counter flow/RPM sensor + APA102 DotStar strip + RTTTL piezo buzzer |
| [`access-panel.json`](../wirestudio/examples/access-panel.json) | ESP32-DevKitC-V4 | Door controller: PN532 NFC reader on I2C, Wiegand keypad, servo latch and a strike-plate relay |
| [`actuator-harness.json`](../wirestudio/examples/actuator-harness.json) | ESP32-DevKitC-V4 | Brake or valve actuator on one 8-way cable: MOSFET H-bridge, feedback pot, tach switch; connector positions land on the bridge's internal nodes |
| [`air-quality-station.json`](../wirestudio/examples/air-quality-station.json) | ESP32-DevKitC-V4 | SCD4x CO2, SHT4x, SGP4x VOC, VEML7700 and BME680 on I2C + PMS5003 particulates on UART2 |
| [`bench-io.json`](../wirestudio/examples/bench-io.json) | ESP32-DevKitC-V4 | The discrete building blocks: status LED, NPN relay driver, MOSFET fan driver on PWM, 12 V divider, 1-Wire level shifter |
| [`blind-stepper.json`](../wirestudio/examples/blind-stepper.json) | ESP32-DevKitC-V4 | 28BYJ-48 geared stepper on a ULN2003 driver |
| [`button-toggles-light.json`](../wirestudio/examples/button-toggles-light.json) | WeMos D1 Mini | Intent-to-device: a button toggles a switch, lowered from `automations` |
| [`co2-display.json`](../wirestudio/examples/co2-display.json) | WeMos D1 Mini | MH-Z19 CO2 on a software UART, TM1637 readout, buzzer alarm above 1200 ppm |
| [`encoder-drives-stepper.json`](../wirestudio/examples/encoder-drives-stepper.json) | ESP32-DevKitC-V4 | Intent-to-device: a rotary encoder's value drives a stepper through a transform |
| [`energy-monitor.json`](../wirestudio/examples/energy-monitor.json) | ESP32-DevKitC-V4 | PZEM-004T over Modbus, an SCT-013 CT clamp on an ADC pin, and an INA219 on a 12 V DC rail |
| [`guarded-button-light.json`](../wirestudio/examples/guarded-button-light.json) | WeMos D1 Mini | Intent-to-device: a button toggles a light only while an enable switch is on |
| [`heltec-v4-gnss-tracker.json`](../wirestudio/examples/heltec-v4-gnss-tracker.json) | Heltec WiFi LoRa 32 V4 | L76K GNSS module on its SH1.25 connector, uplinking position over LoRaWAN via `lorawan-for-esphome` |
| [`lorawan-battery-uplink.json`](../wirestudio/examples/lorawan-battery-uplink.json) | TTGO LoRa32 V1 | Battery voltage uplinked over the LoRaWAN external-component path |
| [`motion-turns-on-light.json`](../wirestudio/examples/motion-turns-on-light.json) | WeMos D1 Mini | Intent-to-device: PIR motion turns a WS2812B on and off |
| [`motor-position.json`](../wirestudio/examples/motor-position.json) | ESP32-DevKitC-V4 | Discrete MOSFET H-bridge on a gearmotor with its feedback pot on an ADC pin |
| [`output-hub.json`](../wirestudio/examples/output-hub.json) | ESP32-DevKitC-V4 | PCA9685 PWM channels on I2C + an SN74HC595 shift register driving a relay |
| [`presence-media-node.json`](../wirestudio/examples/presence-media-node.json) | ESP32-DevKitC-V4 | LD2410 mmWave presence on UART2 + TSOP38238 IR receiver |
| [`solder-fan.json`](../wirestudio/examples/solder-fan.json) | WeMos D1 Mini | 12 V 4-wire PWM fan set by a potentiometer, tach reporting RPM |
| [`spi-io-node.json`](../wirestudio/examples/spi-io-node.json) | ESP32-DevKitC-V4 | MCP23S17 GPIO expander and MCP3008 ADC sharing the VSPI bus |
| [`t-beam-lorawan.json`](../wirestudio/examples/t-beam-lorawan.json) | LilyGO TTGO T-Beam | Standalone LoRaWAN firmware: GPS, AXP192 cell voltage, DHT22, SSD1306 status |
| [`temp-above-turns-on-fan.json`](../wirestudio/examples/temp-above-turns-on-fan.json) | WeMos D1 Mini | Intent-to-device: BME280 temperature above 28 °C turns a fan on (`on_value_range`) |
| [`temp-turns-on-fan.json`](../wirestudio/examples/temp-turns-on-fan.json) | WeMos D1 Mini | Intent-to-device: a multi-channel sensor's temperature channel drives a switch |
| [`usbc-led-strip.json`](../wirestudio/examples/usbc-led-strip.json) | ESP32-DevKitC-V4 | WS2812B strip fed from its own USB-C receptacle with CC pull-downs, out on a JST-XH plug |
| [`vent-damper.json`](../wirestudio/examples/vent-damper.json) | ESP32-C3 SuperMini | DRV8833-class H-bridge on a damper gearmotor, exposed as a reversible fan |
| [`wled-sensor-strip.json`](../wirestudio/examples/wled-sensor-strip.json) | ESP32-DevKitC-V4 | WS2812 strip, button, BME280 and DS18B20; on WLED the sensors are usermods |
| [`xiao-grove-climate.json`](../wirestudio/examples/xiao-grove-climate.json) | Seeed XIAO ESP32C3 | Grove AHT20 on the Grove I2C connector |

Generated artifacts for each are pinned as goldens in
[`tests/golden/`](../tests/golden/). For a per-component / per-board view of
which library entries are exercised by these examples, see
[library-coverage.md](library-coverage.md) (regenerate with
`python scripts/coverage_matrix.py`).
