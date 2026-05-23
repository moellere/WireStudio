# Library reference

[← docs index](index.md)

Every board and component currently shipped. For which entries are
exercised by a bundled example, see
[library-coverage.md](library-coverage.md).

## Boards

`wirestudio/library/boards/`

- `esp32-devkitc-v4` — ESP32 DevKitC V4 (ESP32-WROOM-32, 4MB flash)
- `nodemcu-32s` — NodeMCU-32S (ESP32-WROOM-32, marks I2S-capable pins)
- `ttgo-lora32-v1` — LilyGO TTGO LoRa32 V1 (ESP32 + onboard SX1276 + onboard SSD1306)
- `ttgo-t-beam` — LilyGO TTGO T-Beam v1.x (ESP32 + onboard SX1276 + NEO-6M GPS + AXP192 PMIC + 18650)
- `esp32-c3-devkitm-1` — ESP32-C3-DevKitM-1 (single-core RISC-V, USB-Serial-JTAG, onboard WS2812)
- `esp32-s3-devkitc-1` — ESP32-S3-DevKitC-1 (dual-core Xtensa, native USB, onboard WS2812)
- `esp32cam-ai-thinker` — AI-Thinker ESP32-CAM (ESP32-WROVER-B + OV2640 + microSD)
- `esp32-wrover-cam` — ESP32-WROVER-CAM (Freenove-style, OV2640 with the WROVER pinout)
- `m5stack-atom` — M5Stack Atom Lite / Echo (ESP32-PICO-D4, 24mm cube, onboard SK6812)
- `m5stack-atom-echo` — M5Stack Atom Echo (ESP32-PICO-D4 + SK6812 + I2S mic/speaker)
- `m5stack-atom-matrix` — M5Stack Atom Matrix (ESP32-PICO-D4 + 5x5 SK6812 matrix + MPU6886 IMU + IR)
- `m5stack-atomu` — M5Stack AtomU (ESP32-PICO-D4 USB-A stick + SK6812 + PDM mic + IR)
- `m5stack-atoms3` — M5Stack AtomS3 (ESP32-S3 + onboard 0.85" 128×128 ST7789 + IMU)
- `m5stack-atoms3-lite` — M5Stack AtomS3 Lite (ESP32-S3-FN8 + WS2812 + button + IR)
- `wemos-d1-mini` — WeMos D1 Mini (ESP-12F module, ESP8266)
- `nodemcu-v2` — NodeMCU v2 (ESP-12E/F module, ESP8266, breaks out RX/TX/MISO/MOSI as D9-D12)
- `esp01_1m` — ESP-01S 1MB module / Sonoff Basic-class devices
- `esp8285-1m` — Generic ESP8285 1MB SoC (Athom / Sonoff Basic R3+ / Tuya smart plugs)

## Components

`wirestudio/library/components/`

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
- `mpu6886` — InvenSense MPU6886 6-axis IMU (the onboard IMU on the M5Stack Atom / AtomS3 family, I2C)

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
- `i2s_microphone` — I2S / PDM microphone (SPM1423 on the M5Stack Atom Echo / AtomU, or a standard I2S mic)
- `rtttl` — piezo buzzer + RTTTL melody player (PWM output)
- `remote_transmitter` — IR transmitter / blaster on a single GPIO (the onboard IR LED on the M5Stack Atom family)
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
without bloating `esphome_extras`. See
[`securitypanel.json`](../wirestudio/examples/securitypanel.json) for a
12-sensor MCP23017 wiring or
[`awning-control.json`](../wirestudio/examples/awning-control.json) for a
mix of expander inputs and outputs.

The library spans the device classes used across the
[`moellere/esphome`](https://github.com/moellere/esphome) device
configurations and keeps growing as new device configs land. See
[`START.md` § Library sourcing strategy](../START.md#library-sourcing-strategy)
for the hybrid plan.
