/**
 * WebSerial flashing + serial monitor via esptool-js. Lives in its own module
 * (like usb-detect.ts) so the browser-only esptool-js bundle stays out of
 * vitest's import graph -- flashFirmware() dynamic-imports it.
 *
 * Default flow is an **app-region** flash: write the PlatformIO `firmware.bin`
 * (the app image) at 0x10000 with eraseAll=false. That preserves the existing
 * bootloader/partition table *and the NVS partition* -- the LoRaWAN DevNonce
 * counter lives in NVS, so an app-only re-flash does not reset it (the §2.1
 * fix). For a blank board the caller instead passes the merged factory image
 * (bootloader + partitions + app, from the worker's `/factory` endpoint) at
 * 0x0 with eraseAll=true; provisioning afterwards re-flushes DevNonces, so the
 * wiped NVS is fine. This module is image-agnostic -- the caller picks.
 */
import { isWebSerialSupported } from "./usb-detect";

/** ESP32 Arduino/ESPHome partition layout puts the app image here. */
export const APP_PARTITION_OFFSET = 0x10000;

export interface FlashImage {
  data: Uint8Array;
  address: number;
}

export interface FlashOptions {
  /** Images to write. App-region flash is a single image at APP_PARTITION_OFFSET. */
  images: FlashImage[];
  /**
   * Full-chip erase before writing. Leave false for an app-region re-flash:
   * true wipes NVS (resets DevNonces) and the bootloader, so it must be paired
   * with a full image set + a ChirpStack nonce flush.
   */
  eraseAll?: boolean;
  /** Kept at 115200 so the post-reset serial monitor reads the app at its
   *  native baud without a reconnect. */
  baudrate?: number;
  /** Progress of the write, in bytes. */
  onProgress?: (written: number, total: number) => void;
  /** esptool-js sync/flash chatter. */
  onLog?: (line: string) => void;
  /** Device serial output streamed after the post-flash reset (boot + join logs). */
  onSerial?: (text: string) => void;
}

export interface FlashSession {
  /** Chip name esptool-js reported during flashing, e.g. "ESP32". */
  chipName: string;
  /** Base MAC read from eFuse during flashing, if available. Source for the DevEUI. */
  mac?: string;
  /** Write to the device's serial input -- drives LoRaWAN_ESP32's provisioning prompt. */
  write: (text: string) => Promise<void>;
  /** Stop the serial monitor and release the port. */
  close: () => Promise<void>;
}

/**
 * Trigger the WebSerial port picker, flash `images`, reset into the app, then
 * stream the device's serial output via `onSerial` until the returned
 * `close()` is called. Throws on browser-not-supported, user cancellation, or
 * any flash failure.
 */
export async function flashFirmware(opts: FlashOptions): Promise<FlashSession> {
  if (isWebSerialSupported() !== "yes") {
    throw new Error(
      "WebSerial isn't available in this browser. Try Chrome or Edge on desktop.",
    );
  }
  if (opts.images.length === 0) {
    throw new Error("nothing to flash: no firmware images provided");
  }

  // requestPort() must run from a user gesture; the dialog ensures that.
  const port = await (navigator as Navigator & { serial: { requestPort: () => Promise<unknown> } })
    .serial.requestPort();

  const { ESPLoader, Transport } = await import("esptool-js");

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const transport = new Transport(port as any, false);
  const terminal = opts.onLog
    ? {
        clean: () => {},
        write: (data: string) => opts.onLog?.(stripAnsi(data)),
        writeLine: (data: string) => opts.onLog?.(stripAnsi(data)),
      }
    : undefined;

  const loader = new ESPLoader({
    transport,
    baudrate: opts.baudrate ?? 115200,
    terminal,
    debugLogging: false,
  });

  // main() syncs, runs the stub, and returns the chip name.
  const chipName = await loader.main();
  let mac: string | undefined;
  try {
    mac = await loader.chip.readMac(loader);
  } catch {
    // readMac is best-effort; some pre-stub paths don't expose it.
  }

  await loader.writeFlash({
    fileArray: opts.images.map((image) => ({ data: image.data, address: image.address })),
    // "keep" leaves the bootloader's flash mode/freq/size untouched -- right for
    // an app-region write that must not disturb the existing layout.
    flashMode: "keep",
    flashFreq: "keep",
    flashSize: "keep",
    eraseAll: opts.eraseAll ?? false,
    compress: true,
    reportProgress: (_fileIndex, written, total) => opts.onProgress?.(written, total),
  });

  // Flashing leaves esptool's own reader holding the port's `readable` lock, so
  // a monitor can't acquire a reader on the same stream -- rawRead's getReader()
  // would throw "already locked", get swallowed internally, and return with no
  // output. Cycle the port for a clean reader, start the monitor, THEN reset, so
  // it's listening before the app boots and catches the banner + the
  // LoRaWAN_ESP32 provisioning prompt.
  await transport.disconnect();
  await transport.connect(opts.baudrate ?? 115200);

  let closed = false;
  const decoder = new TextDecoder();
  const monitor = transport
    .rawRead(
      (chunk: Uint8Array) => opts.onSerial?.(decoder.decode(chunk, { stream: true })),
      () => closed,
    )
    .catch((err) => {
      // Surface read failures (locked/lost port) instead of hiding them.
      if (closed) return;
      const msg = err instanceof Error ? err.message : String(err);
      opts.onSerial?.(`\n[serial monitor stopped: ${msg}]\n`);
    });

  // Reset into the app with an explicit EN pulse. esptool's after("hard_reset")
  // only de-asserts EN (setRTS(false)) -- a no-op after the port re-open above,
  // which leaves the chip running the flashing stub (silent). The classic ESP32
  // auto-reset circuit needs EN actually pulsed (RTS) while IO0 (DTR) stays high
  // so it boots the app, not the download ROM. These are control signals (no
  // reads), so they're safe while the monitor holds the read lock.
  await transport.setDTR(false); // IO0 high: normal boot, not download
  await transport.setRTS(true); // EN low: hold in reset
  await sleep(100);
  await transport.setRTS(false); // EN high: release -> app boots into setup()

  const encoder = new TextEncoder();
  return {
    chipName,
    mac,
    write: (text: string) => transport.write(encoder.encode(text)),
    close: async () => {
      closed = true;
      try {
        await transport.disconnect();
      } catch {
        // intentionally ignored: transport may already be closing
      }
      await monitor;
    },
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function stripAnsi(s: string): string {
  // esptool-js log lines carry ANSI color escapes; strip them for a plain <pre>.
  // eslint-disable-next-line no-control-regex
  return s.replace(/\x1b\[[0-9;]*m/g, "");
}
