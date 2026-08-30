# Hardware integration spec

What a manufacturer supplies to get a board or component into the
wirestudio library, and how each piece of data is used. One YAML file
per product, plus a small submission manifest per batch. Files are
validated strictly on load — unknown keys are rejected — so the
schemas below are exact.

## How the data is consumed

Every downstream artifact is generated from these files plus a user's
`design.json`. Each field feeds one or more phases:

| Phase | Consumes |
|---|---|
| Catalog & search | `id`, `name`, `category`, `use_cases`, `aliases`, `image` |
| Pin solving (CSP) | `electrical.pins` (kind, requires_pwm, requires_interrupt), board `gpio_capabilities`, `default_buses` |
| Electrical validation | `electrical.vcc_min/max`, `current_ma_*`, `pull_up`, `passives`, board `rails`, board `current_ma_*` |
| ESPHome YAML + compile | `esphome.required_components`, `esphome.yaml_template`, `params_schema`, board `platformio_board`, `framework`, `chip_variant` |
| Automations | `capability` (provides / accepts / checks) |
| Wiring diagram & schematic | `electrical.pins`, `passives`, `kicad` (symbol, footprint, pin_map) |
| PCB + fab bundle | `kicad.footprint` |
| Enclosure generation | board `enclosure` (pcb dims, mount_holes, ports, component_height_max_mm) |
| LoRaWAN firmware | board `radio`, component `lorawan` |
| Tasmota template | component `tasmota` (pins / bus function map) |

A product with only the required fields still works end-to-end for
YAML generation and wiring; each optional block unlocks the phase it
feeds. More filled-in blocks means a higher listing tier (see
Validation tiers).

## Submission bundle

One directory per batch:

```
submission.yaml            # manifest, not loaded by the studio
components/<id>.yaml       # one per sensor/breakout/module product
boards/<id>.yaml           # one per dev board product
datasheets/<id>.pdf
images/<id>.png            # product photo, square, >= 512px
```

`submission.yaml` carries the commerce metadata that stays out of the
library files (a copyable template ships at
[`docs/submission.template.yaml`](submission.template.yaml)):

```yaml
vendor: Example Corp
contact: integrations@example.com
products:
  - id: example-sensor        # matches the library file id
    mpn: EX-1234
    datasheet: datasheets/example-sensor.pdf
    product_url: https://example.com/ex-1234
    purchase_url: https://shop.example.com/ex-1234
    samples_available: true   # engineering samples for the validated tier
```

## Component spec (`components/<id>.yaml`)

Sensors, actuators, displays, breakouts. A multi-part product (base +
plug-in parts) is one file per part; composite kits can additionally
ship a module file that inserts several parts at once.

```yaml
# --- identity (required; catalog & search) ---
id: example-sensor            # lowercase, digits, dashes; globally unique
name: Example Corp EX-1234 (T/H)
category: sensor              # sensor | input | output | display | expander | ...
use_cases: [temperature, humidity]
aliases: [ex1234]             # alternate names search should match

# --- electrical (required; pin solving + validation + wiring) ---
electrical:
  vcc_min: 1.8                # supply range, volts
  vcc_max: 3.6
  current_ma_typical: 0.6     # active draw; peak covers worst-case bursts
  current_ma_peak: 4
  pins:                       # every pin a user must wire
  - {role: VCC, kind: power}
  - {role: GND, kind: ground}
  - role: SDA
    kind: i2c_sda
    pull_up: {required: true, value: "4.7k", to: VCC}   # omit if on-module
  - role: SCL
    kind: i2c_scl
    pull_up: {required: true, value: "4.7k", to: VCC}
  passives:                   # external parts the wiring diagram must place
  - {kind: capacitor, value: "100nF", between: [VCC, GND], purpose: decoupling}
```

Pin `kind` values in use: `power`, `ground`, `digital_in`,
`digital_out`, `analog_in`, `i2c_sda`, `i2c_scl`, `spi_clk`,
`spi_mosi`, `spi_miso`, `spi_cs`, `uart_tx`, `uart_rx`,
`onewire_data`, `i2s_*`, `hub_ref` (channel of a parent component,
with `parent_library_id`). Flags on a pin: `requires_pwm: true` for
PWM/analog outputs (solver avoids `no_pwm` pins), `requires_interrupt:
true` for edge-counted inputs (solver avoids `no_interrupt` pins),
`voltage` when a pin's level differs from VCC.

```yaml
# --- functionality (required for ESPHome generation) ---
esphome:
  required_components: [i2c]  # ESPHome components the config must include
  yaml_template: |            # Jinja2; params/bus/label are provided
    sensor:
      - platform: example_i2c
        address: "{{ params.address | default('0x40') }}"
        i2c_id: {{ bus.id }}
        temperature:
          name: "{{ label }} Temperature"

params_schema:                # user-tunable knobs, JSON-Schema style
  address:
    type: string
    enum: ["0x40", "0x41"]
    default: "0x40"

# --- automations (optional; trigger/action/condition surface) ---
capability:
  role: sensor                # input | sensor | output | controller
  provides:
  - {event: on_value, kind: value, channel: temperature}
  accepts: []                 # e.g. {action: turn_on, esphome: switch.turn_on}
  checks: []                  # e.g. {predicate: is_on, esphome: switch.is_on}

# --- physical / schematic (optional; unlocks schematic + PCB phases) ---
kicad:
  symbol_lib: Sensor
  symbol: EX1234
  footprint: Package_LGA:EX-1234_2.5x2.5mm
  pin_map: {VCC: VDD}         # library role -> symbol pin name, where they differ

notes: "3V3 only. On 5V boards, place behind a level shifter."

# --- tasmota (optional; unlocks the Tasmota template target) ---
# Maps pin roles to Tasmota GPIO function names (see the tasmota
# target's FUNC table). UART-attached parts map bus slots instead.
# I2C sensors need no block: Tasmota autodetects them from the bus.
tasmota:
  pins: {DATA: DHT22}         # or e.g. {OUT: Relay}, {IN: Switch}
  # bus: {rx: CSE7766_RX, tx: CSE7766_TX}
```

If no upstream KiCad symbol exists, name the closest generic symbol
(e.g. `Connector_Generic:Conn_01x04`) and set `value` so the
schematic prints the real part name.

## Board spec (`boards/<id>.yaml`)

Dev boards and modules that host the MCU.

```yaml
# --- identity + build (required) ---
id: example-devkit
name: Example Corp DevKit v1
mcu: esp32                    # esp8266 | esp32 today; any ESPHome-supported MCU family
chip_variant: esp32c3         # PlatformIO chip variant
framework: arduino            # arduino | esp-idf
platformio_board: example_devkit
flash_size_mb: 4              # see "Flash size" below -- get this wrong upward and the board boot-loops
image: https://example.com/img/devkit.png

# --- power (required; current budget validation) ---
current_ma_typical: 80        # bare-board draw, Wi-Fi associated
current_ma_peak: 350          # TX burst worst case
rails:
- {name: "5V", voltage: 5.0, source: usb}
- {name: "3V3", voltage: 3.3, source: onboard_regulator}
- {name: "GND", voltage: 0.0}

# --- pinout (required; this is what the solver assigns from) ---
gpio_capabilities:
  GPIO0: [gpio, strap, boot_high, pwm]
  GPIO1: [gpio, adc, adc1, pwm]
  GPIO20: [gpio, uart_rx, serial_rx]
  GPIO21: [gpio, uart_tx, serial_tx]

default_buses:                # canonical bus pins users expect
  i2c: {sda: GPIO6, scl: GPIO7}

onboard_peripherals: {}       # parts already on the PCB, seeded into new designs
```

GPIO tags: capability tags (`gpio`, `pwm`, `adc`, `adc1`, `adc2`,
`touch`, `dac`, `uart_tx`, `uart_rx`) plus restriction tags —
`strap` + `boot_high`/`boot_low` (level required at boot),
`pull_up_external` / `pull_down_external` (fixed board resistor),
`serial_tx`/`serial_rx` (shared with the USB console), `input_only`,
`no_pull_internal`, `no_pwm`, `no_i2c`, `no_interrupt`, `adc_max_1v`.
Tag accuracy is the single highest-value thing a vendor can review:
strap and ADC2/Wi-Fi conflicts are exactly what users can't see in a
pinout diagram.

```yaml
# --- physical (optional; unlocks enclosure generation) ---
# Origin at the PCB's bottom-left corner, top view; +X along length,
# +Y along width. All millimetres.
enclosure:
  pcb: {length_mm: 54.4, width_mm: 28.6, thickness_mm: 1.6}
  mount_holes:
  - {x_mm: 3.0, y_mm: 14.3, hole_diameter_mm: 3.2}
  ports:                      # connectors needing a wall cutout
  - kind: usb_c               # usb_micro | usb_c | usb_b | barrel_jack | sma | jst | header
    edge: short_a             # short_a (x=0) | short_b | long_a (y=0) | long_b
    offset_mm: 10.3           # from the edge's start
    width_mm: 9.0
    height_mm: 3.2
    height_above_pcb_mm: 1.5  # connector body height above PCB top
  component_height_max_mm: 13.0

# --- schematic (optional) ---
kicad:
  symbol_lib: RF_Module
  symbol: ESP32-WROOM-32
  footprint: RF_Module:ESP32-WROOM-32

# --- LoRa boards only ---
radio:
  chip: sx1262                # sx1276 | sx1278 | sx1262
  radiolib_class: SX1262
  pins: {cs: GPIO8, rst: GPIO12, dio1: GPIO14, busy: GPIO13}
  tcxo_voltage: 1.8
  dio2_as_rf_switch: true
```

### Flash size

`flash_size_mb` is emitted into the ESPHome config and drives the
partition table, so it is the one field where a wrong value bricks
rather than degrades. The asymmetry matters:

- **Under-declaring wastes flash.** A 16MB board declared as 8MB loses
  half its OTA slots and nothing else.
- **Over-declaring boot-loops the board.** Declaring 8MB on a 4MB
  PICO-D4 is how a Heltec V2 was bricked in 0.26.x.

So when in doubt, declare the smallest size the board ships with, and
say so in a comment. Several bundled boards carry exactly that note.

**Boards sold in multiple flash sizes under one name are the trap.** The
ESP32-S3-DevKitC-1 ships as N8/N8R2/N8R8 (8MB) *and* N32R16V (32MB); no
static value is right for every unit. Pin the floor and comment that it
must not be raised.

A design that has *measured* its own unit claims the rest with a
per-design override, which wins over the board file in both the ESPHome
and LoRaWAN generators:

```json
"board": { "library_id": "esp32-s3-devkitc-1", "mcu": "esp32", "flash_size_mb": 32 }
```

Allowed values are 4, 8, 16 and 32 — the sizes both generators can name a
partition table for. Raising it above the board file's value validates
with a `flash_size_override_above_board` warning, because that is the
direction that boot-loops; lowering it is safe and silent. Switching the
design's board drops the override, since a size measured on one board
says nothing about another.

To verify against silicon, the reliable route is the ESP-IDF bootloader,
which prints the real size at boot:

```
I (33) boot.esp32s3: SPI Flash Size : 16MB
```

That line only appears on ESP-IDF builds — an Arduino-framework board
prints ROM output and nothing about flash. `esptool flash-id` reads it
directly, but needs the chip in download mode, which auto-reset over a
network RFC2217 link does not reliably achieve; drive the board's
boot/reset pins, or run esptool locally over USB.

## Validation tiers

- **spec** — file review only. Product is listed and generates
  YAML/wiring; marked as unverified.
- **reviewed** — the vendor has confirmed the electrical block and
  GPIO tags against the design files. Marked vendor-reviewed.
- **validated** — we tested an engineering sample end-to-end: pin
  solve, YAML generation, ESPHome compile, flash, runtime behavior,
  and where the blocks exist, schematic/PCB export and enclosure fit.
  Marked validated in the picker.

Reference implementations: `wirestudio/library/components/bme280.yaml`
(complete component) and `wirestudio/library/boards/esp32-devkitc-v4.yaml`
(complete board including enclosure geometry).
