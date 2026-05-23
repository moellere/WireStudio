import { describe, expect, it } from "vitest";
import {
  bootstrapDesign,
  candidateBoardsFor,
  chipFamily,
  normalizeChipFamily,
  type DetectedChip,
} from "./bootstrap";
import type { BoardSummary } from "../types/api";

const boards: BoardSummary[] = [
  { id: "esp32-devkitc-v4", name: "ESP32-DevKitC-V4", mcu: "esp32", chip_variant: "esp32", framework: "arduino", platformio_board: "esp32dev", flash_size_mb: 4, rail_names: ["5V", "3V3", "GND"], image: "" },
  { id: "nodemcu-32s",      name: "NodeMCU-32S",      mcu: "esp32", chip_variant: "esp32", framework: "arduino", platformio_board: "nodemcu-32s", flash_size_mb: 4, rail_names: ["5V", "3V3", "GND"], image: "" },
  { id: "ttgo-lora32-v1",   name: "TTGO LoRa32 V1",   mcu: "esp32", chip_variant: "esp32", framework: "arduino", platformio_board: "ttgo-lora32-v1", flash_size_mb: 4, rail_names: ["5V", "3V3", "GND"], image: "" },
  { id: "wemos-d1-mini",    name: "WeMos D1 Mini",    mcu: "esp8266", chip_variant: "esp8266", framework: "arduino", platformio_board: "d1_mini", flash_size_mb: 4, rail_names: ["5V", "3V3", "GND"], image: "" },
  { id: "esp01_1m",         name: "ESP-01S 1MB",      mcu: "esp8266", chip_variant: "esp8266", framework: "arduino", platformio_board: "esp01_1m", flash_size_mb: 1, rail_names: ["5V", "3V3", "GND"], image: "" },
];

describe("normalizeChipFamily", () => {
  it("strips dashes and lowercases", () => {
    expect(normalizeChipFamily("ESP32-S3")).toBe("esp32s3");
    expect(normalizeChipFamily("ESP32-C3")).toBe("esp32c3");
    expect(normalizeChipFamily("ESP8266")).toBe("esp8266");
    expect(normalizeChipFamily("esp32")).toBe("esp32");
  });

  it("handles whitespace and underscores", () => {
    expect(normalizeChipFamily("ESP32 S3")).toBe("esp32s3");
    expect(normalizeChipFamily("ESP32_C3")).toBe("esp32c3");
  });
});

describe("chipFamily", () => {
  it("folds ESP32 package codes back to plain esp32", () => {
    // esptool returns detailed descriptions; these are all classic ESP32.
    expect(chipFamily("ESP32-PICO-D4 (revision 1)")).toBe("esp32");
    expect(chipFamily("ESP32-D0WD-V3")).toBe("esp32");
    expect(chipFamily("ESP32")).toBe("esp32");
  });

  it("keeps the real sub-family suffix", () => {
    expect(chipFamily("ESP32-S3 (QFN56) (revision v0.2)")).toBe("esp32s3");
    expect(chipFamily("ESP32-C3")).toBe("esp32c3");
    expect(chipFamily("ESP32-C6")).toBe("esp32c6");
    expect(chipFamily("ESP32-P4")).toBe("esp32p4");
  });

  it("folds ESP8285 into the esp8266 family", () => {
    expect(chipFamily("ESP8285")).toBe("esp8266");
    expect(chipFamily("ESP8266")).toBe("esp8266");
  });
});

describe("candidateBoardsFor", () => {
  it("returns boards in the matched chip family", () => {
    const cs = candidateBoardsFor(boards, "ESP32");
    expect(cs.map((b) => b.id)).toEqual(["esp32-devkitc-v4", "nodemcu-32s", "ttgo-lora32-v1"]);
  });

  it("matches a detailed esptool chip description to its family", () => {
    // Regression: the M5Stack Atom Echo reports as ESP32-PICO-D4 and used
    // to match nothing, dumping the user into the full board list.
    const cs = candidateBoardsFor(boards, "ESP32-PICO-D4 (revision 1)");
    expect(cs.map((b) => b.id)).toEqual(["esp32-devkitc-v4", "nodemcu-32s", "ttgo-lora32-v1"]);
  });

  it("matches dashes and case", () => {
    const cs = candidateBoardsFor(boards, "ESP-8266");
    expect(cs.map((b) => b.id)).toEqual(["wemos-d1-mini", "esp01_1m"]);
  });

  it("does not cross-match esp32 sub-families", () => {
    // No esp32s3 board in this set, so an S3 detection yields no candidates
    // (rather than wrongly matching the plain-esp32 boards).
    expect(candidateBoardsFor(boards, "ESP32-S3").map((b) => b.id)).toEqual([]);
  });
});

describe("bootstrapDesign", () => {
  const chip: DetectedChip = { chipName: "ESP32", mac: "AA:BB:CC:DD:EE:FF" };

  it("produces a schema-conformant skeleton", () => {
    const d = bootstrapDesign(boards[0], chip);
    expect(d.schema_version).toBe("0.1");
    expect(d.id).toBe("new-device");
    expect(d.board).toEqual({ library_id: "esp32-devkitc-v4", mcu: "esp32", framework: "arduino" });
    expect(d.power).toMatchObject({ supply: "usb-5v", rail_voltage_v: 5.0 });
    expect(d.components).toEqual([]);
    expect(d.buses).toEqual([]);
    expect(d.connections).toEqual([]);
    expect(d.fleet).toMatchObject({ device_name: "new-device" });
    expect((d.fleet as { secrets_ref: Record<string, string> }).secrets_ref.api_key).toBe("!secret api_key");
  });

  it("includes a device_bootstrap warning carrying chip name and MAC", () => {
    const d = bootstrapDesign(boards[0], chip);
    const warnings = d.warnings as Array<{ code: string; text: string; level: string }>;
    expect(warnings.length).toBe(1);
    expect(warnings[0].code).toBe("device_bootstrap");
    expect(warnings[0].level).toBe("info");
    expect(warnings[0].text).toContain("ESP32");
    expect(warnings[0].text).toContain("AA:BB:CC:DD:EE:FF");
  });

  it("omits the MAC from the warning when not detected", () => {
    const d = bootstrapDesign(boards[0], { chipName: "ESP32-S3" });
    const text = (d.warnings as Array<{ text: string }>)[0].text;
    expect(text).toContain("ESP32-S3");
    expect(text).not.toContain("MAC");
  });
});
