import type { BoardSummary, Design } from "../types/api";

/** Info esptool-js gives us back about a freshly-connected chip. */
export interface DetectedChip {
  /** Chip name as returned by esptool-js, e.g. "ESP32", "ESP32-S3". */
  chipName: string;
  /** MAC address if we managed to read it. */
  mac?: string;
}

/**
 * Map esptool-js's chip name to the lowercased no-dash variant the studio
 * library uses in `chip_variant`. ESP32-S3 -> esp32s3, ESP8266 -> esp8266.
 */
export function normalizeChipFamily(chipName: string): string {
  return chipName.toLowerCase().replace(/[-_\s]/g, "");
}

/** Pick the boards in the library that match the detected chip family. */
export function candidateBoardsFor(boards: BoardSummary[], chipName: string): BoardSummary[] {
  const target = normalizeChipFamily(chipName);
  return boards.filter((b) => normalizeChipFamily(b.chip_variant) === target);
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
