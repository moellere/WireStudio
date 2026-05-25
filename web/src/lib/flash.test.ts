import { afterEach, describe, expect, it } from "vitest";
import { APP_PARTITION_OFFSET, flashFirmware } from "./flash";

describe("flashFirmware", () => {
  afterEach(() => {
    // Drop any stubbed serial so other tests see a clean navigator.
    delete (navigator as unknown as { serial?: unknown }).serial;
  });

  it("app partition offset is the standard ESP32 app slot", () => {
    expect(APP_PARTITION_OFFSET).toBe(0x10000);
  });

  it("rejects when WebSerial is unavailable (jsdom has no navigator.serial)", async () => {
    await expect(
      flashFirmware({ images: [{ data: new Uint8Array([1]), address: 0 }] }),
    ).rejects.toThrow(/WebSerial/);
  });

  it("rejects an empty image set before touching the port", async () => {
    let requested = false;
    (navigator as unknown as { serial: unknown }).serial = {
      requestPort: async () => {
        requested = true;
        return {};
      },
    };
    await expect(flashFirmware({ images: [] })).rejects.toThrow(/nothing to flash/);
    expect(requested).toBe(false); // guard fires before the port picker
  });
});
