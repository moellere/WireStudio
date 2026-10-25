# Third-party sources and licences

wirestudio is MIT ([`LICENSE`](LICENSE)). This file records everything in
the tree, in the artifacts it generates, or in the images it ships that
comes from somewhere else: the source, what was taken, its licence, and
how it is used. Identifiers, enum values and pin numbers are facts, not
expression; the sources are recorded all the same, so a reader can check
the derivation and the terms.

## Data derived into the tree

| Where in the tree | What | Source | Licence |
|---|---|---|---|
| `wirestudio/targets/tasmota.py` | GPIO function ids (`UserSelectablePins` enum index `<< 5` plus unit) and the per-chip template slot order (`ESP32_TEMPLATE_TO_PHY`) | `tasmota/tasmota_template.h` in [arendst/Tasmota](https://github.com/arendst/Tasmota); values cross-checked against the [blakadder template database](https://templates.blakadder.com), nothing copied from it | GPL-3.0-only |
| `wirestudio/targets/wled.py`; `wled:` blocks in `wirestudio/library/components/*.yaml` | `cfg.json` keys and the LED, colour-order and button type codes; usermod directory names, `-D` defines, `lib_deps` and the `um` config keys each usermod reads | `wled00/const.h`, `wled00/cfg.cpp` and `usermods/*` in [wled/WLED](https://github.com/wled/WLED) at v0.15.2 | EUPL-1.2 |
| `wirestudio/api/meshtastic.py` | board to firmware-variant map | the `[env:...]` names under `variants/` in [meshtastic/firmware](https://github.com/meshtastic/firmware) | GPL-3.0-only |
| `wirestudio/api/circuitpython.py` | board ids and the exact / pin-compatible-fallback tiering | `ports/espressif/boards` in [adafruit/circuitpython](https://github.com/adafruit/circuitpython) | MIT |
| `wirestudio/api/micropython.py` | port board ids and PSRAM / flash variants | the ESP32 and ESP8266 port boards in [micropython/micropython](https://github.com/micropython/micropython) and the download pages on micropython.org | MIT |
| `kicad:` blocks in every library component and board file | symbol library and symbol names, symbol pin names (`pin_map`), footprint names | [kicad-symbols](https://gitlab.com/kicad/libraries/kicad-symbols) and [kicad-footprints](https://gitlab.com/kicad/libraries/kicad-footprints) at 8.0.0. The libraries themselves are not in the tree: the `kicad-*` workflows and `Dockerfile.pcb` clone them at that tag | CC-BY-SA-4.0 with the KiCad libraries exception (a design that uses the symbols and footprints is not adapted material) |
| `wirestudio/enclosure/yapp/YAPPgenerator_v3.scad` | the YAPP_Box generator, vendored unmodified and inlined into every generated enclosure `.scad`; its licence ships beside it | [mrWheel/YAPP_Box](https://github.com/mrWheel/YAPP_Box) at commit `f9400c4` (generator v3.3.8) | MIT |
| `tests/fixtures/Sensor.kicad_sym` | a one-symbol library written for the importer test, modelled on the BME280 symbol's pin names and footprint reference | in-house, after kicad-symbols | MIT (this repository) |
| `esphome:` blocks in every library component file; `wirestudio/generate/yaml_gen.py` | integration names, config keys and the YAML shape ESPHome accepts | [esphome/esphome](https://github.com/esphome/esphome); the gates pin one release. The studio emits configuration and vendors no ESPHome source | ESPHome License (MIT for the Python side, GPL-3.0 for the C++ runtime) |
| `wirestudio/library/boards/*.yaml` | pinouts, strap pins, rails, default buses, board outlines and mount holes; header pin order in each `kicad.pin_map` | the vendors' datasheets and schematics (Espressif, Heltec, LilyGO, M5Stack, Seeed, WeMos, AI-Thinker, NodeMCU, Freenove, Nologo), cited inline where a value needed one; each header order cites the vendor repository and commit it was transcribed from | facts |
| `wirestudio/library/components/*.yaml` | electrical limits, pin kinds, pull-up needs, passives | the parts' datasheets and the ESPHome component docs | facts |

## Named in generated firmware, fetched at the user's build

The generators write these as dependencies; PlatformIO or ESPHome fetches
them when the user (or a CI gate) builds. None is vendored.

| Named by | Library | Licence |
|---|---|---|
| the LoRaWAN target (`templates/platformio.ini.j2`) | [RadioLib](https://github.com/jgromes/RadioLib) | MIT |
| the LoRaWAN target | [LoRaWAN_ESP32](https://github.com/ropg/LoRaWAN_ESP32) | MIT |
| `lorawan:` blocks on `axp192`, `dht`, `ssd1306`, `uart_gps` | [XPowersLib](https://github.com/lewisxhe/XPowersLib) (MIT), [Adafruit DHT sensor library](https://github.com/adafruit/DHT-sensor-library) (MIT), [Adafruit SSD1306](https://github.com/adafruit/Adafruit_SSD1306) (BSD-3-Clause), [TinyGPSPlus](https://github.com/mikalhart/TinyGPSPlus) (LGPL-2.1-or-later) | as listed |
| `wled:` usermod blocks on `bme280`, `bmp280`, `sht3xd`, `ds18b20`, `dht`, `vl53l0x`, `i2s_microphone`, `ld2410`, `ssd1306`, `st7789`, `mpu6050`, `bme680` | [BME280](https://github.com/finitespace/BME280) (GPL-3.0), [SHT85](https://github.com/RobTillaart/SHT85) (MIT), [OneWire](https://github.com/PaulStoffregen/OneWire) (MIT-style notice in the source), [DHT_nonblocking](https://github.com/alwynallan/DHT_nonblocking) (GPL-3.0), [VL53L0X](https://github.com/pololu/vl53l0x-arduino) (MIT), [arduinoFFT](https://github.com/kosme/arduinoFFT) (GPL-3.0), [ld2410](https://github.com/ncmreynolds/ld2410) (LGPL-2.1), [U8g2](https://github.com/olikraus/u8g2) (BSD-2-Clause), [TFT_eSPI](https://github.com/Bodmer/TFT_eSPI) (FreeBSD and MIT, per its licence file), [MPU6050](https://github.com/ElectronicCats/mpu6050) (MIT), [Bolder Flight Systems Eigen](https://github.com/bolderflight/eigen) (MIT, wrapping Eigen under MPL-2.0), [BSEC Software Library](https://github.com/boschsensortec/BSEC-Arduino-library) (Bosch's own licence: binary only, for use with Bosch sensors) | as listed |
| `circuitpython:` blocks, copied into `CIRCUITPY/lib` | the `adafruit_*` and `neopixel` libraries of the [Adafruit CircuitPython Bundle](https://github.com/adafruit/Adafruit_CircuitPython_Bundle) | MIT |
| `micropython:` blocks, installed by `mip` | [micropython-lib](https://github.com/micropython/micropython-lib) `ssd1306`, `logging`, `lora-sx127x` and `lora-sync` (MIT); [BME280](https://github.com/robert-hh/BME280), [BME680-Micropython](https://github.com/robert-hh/BME680-Micropython), [micropython_ahtx0](https://github.com/targetblank/micropython_ahtx0), [micropython-bmp280](https://github.com/dafvid/micropython-bmp280), [pyb_ina219](https://github.com/chrisb2/pyb_ina219), [micropython-mcp23008](https://github.com/mcauser/micropython-mcp23008), [micropython-mcp23017](https://github.com/mcauser/micropython-mcp23017), [micropython-mpu9x50](https://github.com/micropython-IMU/micropython-mpu9x50), [micropython-adafruit-pca9685](https://github.com/adafruit/micropython-adafruit-pca9685), [MicroPython_SCD4X](https://github.com/peter-l5/MicroPython_SCD4X), [micropython-sht31](https://github.com/kfricke/micropython-sht31), [MicroPython_SHT4X](https://github.com/jposada202020/MicroPython_SHT4X), [micropython-adafruit-tsl2561](https://github.com/adafruit/micropython-adafruit-tsl2561), [veml7700](https://github.com/palouf34/veml7700), [micropython-max7219](https://github.com/mcauser/micropython-max7219), [micropython-ili9341](https://github.com/rdagger/micropython-ili9341), [st7789py_mpy](https://github.com/russhughes/st7789py_mpy), [ads1x15](https://github.com/robert-hh/ads1x15), [hx711](https://github.com/robert-hh/hx711), [micropython_ir](https://github.com/peterhinch/micropython_ir), [upy-rtttl](https://github.com/dhylands/upy-rtttl) (MIT, some by the notice in the source); [vl53l0x](https://github.com/kevinmcaleer/vl53l0x) (BSD-3-Clause) | as listed |
| the ESPHome generator, for the external-component LoRaWAN path | [lorawan-for-esphome](https://github.com/moellere/lorawan-for-esphome), pinned by commit | MIT |
| the `cc1101` component's notes | the `radiolib_cc1101` ESPHome fork, which the user adds as an `external_components` entry; the generator does not emit it | per that fork |

A firmware the user builds from these is the user's: its licence
follows from the libraries it links, and a WLED build with the BME280,
DHT or audioreactive usermod links GPL-3.0 code; one with the BME680
links Bosch's binary BSEC library under its own terms.

## Compiled into the web bundle

`web/package.json` names the runtime dependencies Vite bundles into
`web/dist`, which the images serve from `/app/web-dist`.

| Package | Licence |
|---|---|
| react, react-dom | MIT |
| lucide-react | ISC |
| esptool-js | Apache-2.0 |
| @meshtastic/core, @meshtastic/transport-web-serial | GPL-3.0-only |
| @meshtastic/protobufs | GPL-3.0 |
| @fontsource-variable/inter (Inter), @fontsource/jetbrains-mono (JetBrains Mono) | OFL-1.1 |

The Meshtastic client libraries are GPL-3.0, and the built bundle
contains them. Distributing the bundle or an image that serves it
carries the GPL-3.0's terms for that code, including source
availability; this repository is that source. The studio's own code
stays MIT.

Development dependencies (Vite, TypeScript, vitest, ESLint) are not
shipped.

## Fetched into the images at build

| Image | What | Licence |
|---|---|---|
| `Dockerfile` | `python:3.11-slim` base; `node:20-alpine` in the build stage only; the Python dependencies in `pyproject.toml` | per each; the Python packages carry their licence in their own metadata (`pip show`) |
| `Dockerfile` (`-lorawan` variant) | PlatformIO and the LoRaWAN firmware's libraries above, pre-warmed | PlatformIO Apache-2.0; libraries as above |
| `Dockerfile.pcb` | `kicad/kicad:8.0` base (KiCad, with `pcbnew`'s Python bindings) | GPL-3.0 |
| `Dockerfile.pcb` | kicad-symbols and kicad-footprints at 8.0.0 | CC-BY-SA-4.0 with the KiCad libraries exception |
| `Dockerfile.pcb` | Eclipse Temurin 25 JRE | GPL-2.0 with Classpath Exception |
| `Dockerfile.pcb` | the [Freerouting](https://github.com/freerouting/freerouting) 2.2.4 jar, pinned by SHA-256 | GPL-3.0 |

## Relayed, not stored

The firmware proxies stream upstream release binaries to the user's
browser for flashing and keep nothing: Meshtastic (GPL-3.0) from
meshtastic.github.io, CircuitPython (MIT) from
downloads.circuitpython.org, MicroPython (MIT) from micropython.org.
WLED builds clone the release into the firmware cache, which is runtime
state, not the tree. The ChirpStack (MIT), JLCPCB, Thingiverse,
print-warden and fleet-for-esphome integrations are API clients; no
code from those services is in the tree.
