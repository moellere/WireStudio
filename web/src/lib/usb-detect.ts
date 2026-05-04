/**
 * Thin wrapper around esptool-js's chip detection. Lives in its own module
 * so the (browser-only) esptool-js bundle isn't pulled into vitest's import
 * graph -- detectChip() dynamic-imports it.
 */
import type { DetectedChip } from "./bootstrap";

export type WebSerialSupported = "yes" | "no";

export function isWebSerialSupported(): WebSerialSupported {
  return typeof navigator !== "undefined" && "serial" in navigator ? "yes" : "no";
}

export interface DetectOptions {
  baudrate?: number;
  /** Optional sink for the chatty log lines esptool-js emits during sync. */
  onLog?: (line: string) => void;
}

/**
 * Trigger the WebSerial port-picker, run esptool-js's connect+detect, then
 * disconnect. Throws on browser-not-supported, user cancellation, or any
 * sync failure.
 */
export async function detectChip(opts: DetectOptions = {}): Promise<DetectedChip> {
  if (isWebSerialSupported() !== "yes") {
    throw new Error(
      "WebSerial isn't available in this browser. Try Chrome or Edge on desktop.",
    );
  }
  // requestPort() must be called from a user gesture; the dialog ensures that.
  const port = await (navigator as Navigator & { serial: { requestPort: () => Promise<unknown> } })
    .serial.requestPort();

  // Dynamic import keeps esptool-js out of the test-time bundle.
  const { ESPLoader, Transport } = await import("esptool-js");

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const transport = new Transport(port as any, true);
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

  try {
    // main() does sync, runs the stub, returns the chip name string.
    const chipName = await loader.main();
    let mac: string | undefined;
    try {
      // readMac is optional -- some pre-stub paths don't expose it.
      mac = await loader.chip.readMac(loader);
    } catch {
      // intentionally ignored
    }
    return { chipName, mac };
  } finally {
    try {
      await transport.disconnect();
    } catch {
      // intentionally ignored: transport may already be closed
    }
  }
}

function stripAnsi(s: string): string {
  // esptool-js log lines often contain ANSI color escapes; strip them so the
  // dialog's <pre> stays readable.
  // eslint-disable-next-line no-control-regex
  return s.replace(/\x1b\[[0-9;]*m/g, "");
}
