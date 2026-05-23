import type { BoardSummary, Design } from "../types/api";

/** Info esptool-js gives us back about a freshly-connected chip. */
export interface DetectedChip {
  /** Chip name as returned by esptool-js, e.g. "ESP32", "ESP32-S3". */
  chipName: string;
  /** MAC address if we managed to read it. */
  mac?: string;
}

/** Lowercase and drop every separator/punctuation char. */
export function normalizeChipFamily(chipName: string): string {
  return chipName.toLowerCase().replace(/[^a-z0-9]/g, "");
}

/**
 * Reduce a chip name to the canonical family the library's `chip_variant`
 * uses. esptool returns detailed descriptions -- "ESP32-PICO-D4
 * (revision 1)", "ESP32-D0WD-V3", "ESP32-S3 (QFN56) (revision v0.2)" --
 * but the library only distinguishes families (esp32, esp32s3, esp32c3,
 * esp32c6, esp8266, ...). So we keep the real sub-family suffix (S3/C3/
 * C6/H2/P4) and fold package codes (PICO-D4, D0WD) back to plain esp32.
 * ESP8285 is an ESP8266 core, so it folds to esp8266.
 */
export function chipFamily(chipName: string): string {
  const n = normalizeChipFamily(chipName);
  if (n.startsWith("esp8266") || n.startsWith("esp8285")) return "esp8266";
  const m = n.match(/^esp32(s\d|c\d|h\d|p\d)?/);
  return m ? "esp32" + (m[1] ?? "") : n;
}

/** Pick the boards in the library whose chip family matches the detection. */
export function candidateBoardsFor(boards: BoardSummary[], chipName: string): BoardSummary[] {
  const target = chipFamily(chipName);
  return boards.filter((b) => chipFamily(b.chip_variant) === target);
}

/**
 * Build a minimal `design.json` for a freshly-detected board. The user lands
 * in the design view with no components; the warning explains what was
 * detected and what to do next.
 */
export function bootstrapDesign(board: BoardSummary, chip: DetectedChip): Design {
  const macSuffix = chip.mac ? `, MAC ${chip.mac}` : "";
  return {
    schema_version: "0.1",
    id: "new-device",
    name: "New device",
    description: `Bootstrapped via USB device detection from a ${chip.chipName}.`,
    board: {
      library_id: board.id,
      mcu: board.mcu,
      framework: board.framework,
    },
    power: {
      supply: "usb-5v",
      rail_voltage_v: 5.0,
      budget_ma: 500,
    },
    requirements: [],
    components: [],
    buses: [],
    connections: [],
    passives: [],
    warnings: [
      {
        level: "info",
        code: "device_bootstrap",
        text:
          `Bootstrapped from USB-detected chip ${chip.chipName}${macSuffix}. ` +
          "Add components from the inspector to start designing.",
      },
    ],
    esphome_extras: { logger: {} },
    fleet: {
      device_name: "new-device",
      tags: [],
      secrets_ref: {
        wifi_ssid: "!secret wifi_ssid",
        wifi_password: "!secret wifi_password",
        api_key: "!secret api_key",
      },
    },
  };
}
