/**
 * Host side of LoRaWAN serial provisioning. The firmware (LoRaWAN_ESP32's
 * `persist.manage()`) prompts over serial when NVS is empty; this answers those
 * prompts with values ChirpStack issued, so the device joins without anyone
 * typing keys by hand.
 *
 * Pure + framework-free so it's unit-testable: the state machine takes a
 * `write` callback and is `feed()`-driven from the serial monitor stream.
 */

export interface ProvisionValues {
  band: string; // "US915"
  sub_band: number; // 2
  join_eui: string; // 16 hex
  dev_eui: string; // 16 hex
  app_key: string; // 32 hex
}

/**
 * Derive a EUI-64 DevEUI from a MAC-48 by inserting 0xFFFE in the middle, the
 * standard MAC->EUI-64 mapping. Accepts "10:52:1c:66:b6:e0" or "10521c66b6e0".
 */
export function macToEui64(mac: string): string {
  const hex = mac.replace(/[^0-9a-fA-F]/g, "").toLowerCase();
  if (hex.length !== 12) {
    throw new Error(`expected a 12-hex-digit MAC, got "${mac}"`);
  }
  return `${hex.slice(0, 6)}fffe${hex.slice(6)}`;
}

interface Step {
  /** Matches the device's prompt line. */
  prompt: RegExp;
  /** The line to send in reply (newline appended by the driver). */
  answer: (v: ProvisionValues) => string;
}

// LoRaWAN_ESP32's provision() prompt order. nwkKey == appKey for LoRaWAN 1.0.x
// (one root key), matching what we register in ChirpStack's nwk_key field.
const STEPS: Step[] = [
  { prompt: /Enter LoRaWAN band/i, answer: (v) => v.band },
  { prompt: /subband/i, answer: (v) => String(v.sub_band) },
  { prompt: /joinEUI/i, answer: (v) => v.join_eui },
  { prompt: /devEUI/i, answer: (v) => v.dev_eui },
  { prompt: /appKey/i, answer: (v) => v.app_key },
  { prompt: /nwkKey/i, answer: (v) => v.app_key },
];

export interface SerialProvisioner {
  /** Feed serial output; writes the next answer when its prompt appears. */
  feed: (chunk: string) => void;
  /** True once every prompt has been answered. */
  done: () => boolean;
}

/**
 * Build a provisioner that watches the serial stream and answers each prompt in
 * order. `write` sends a line to the device (this adds the newline).
 * `onStep` (optional) reports progress for the UI.
 */
export function createSerialProvisioner(
  values: ProvisionValues,
  write: (line: string) => void,
  onStep?: (index: number, total: number) => void,
): SerialProvisioner {
  let step = 0;
  let buffer = "";

  function advance() {
    // A prompt may already be sitting in the buffer; answer as many as match.
    while (step < STEPS.length && STEPS[step].prompt.test(buffer)) {
      write(STEPS[step].answer(values) + "\n");
      step += 1;
      buffer = ""; // prompts are sequential; reset so we match the next one fresh
      onStep?.(step, STEPS.length);
    }
  }

  return {
    feed(chunk: string) {
      buffer += chunk;
      advance();
    },
    done() {
      return step >= STEPS.length;
    },
  };
}
