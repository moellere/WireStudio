import { afterEach, describe, expect, it, vi } from "vitest";
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

vi.mock("../api/client", () => ({
  api: {
    workbenchOutput: vi.fn(),
    workbenchVerifyBoot: vi.fn(),
  },
}));

describe("watchSlot", () => {
  it("relays new recorder lines once each and hands over the boot verdict", async () => {
    const { api } = await import("../api/client");
    const { watchSlot } = await import("./flash");
    const output = api.workbenchOutput as unknown as ReturnType<typeof vi.fn>;
    output
      .mockResolvedValueOnce({ slot: "S1", lines: [{ ts: 1, text: "ets Jul 29 2019" }] })
      .mockResolvedValue({ slot: "S1", lines: [{ ts: 1, text: "ets Jul 29 2019" }, { ts: 2, text: "setup() finished successfully!\n" }] });
    (api.workbenchVerifyBoot as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, framework: "esphome", booted: true, checks: [] });
    const serial: string[] = [];
    const boots: unknown[] = [];
    await watchSlot("S1", 100, { framework: "esphome", onBoot: (r) => boots.push(r), onSerial: (t) => serial.push(t), watchSeconds: 1.2 });
    expect(serial).toEqual(["ets Jul 29 2019\n", "setup() finished successfully!\n"]);
    expect(boots).toEqual([{ ok: true, framework: "esphome", booted: true, checks: [] }]);
    expect((api.workbenchVerifyBoot as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toEqual({ slot: "S1", framework: "esphome", since: 100 });
  });

  it("reports a failed verify as a result and stops relaying when the bench goes away", async () => {
    const { api } = await import("../api/client");
    const { watchSlot } = await import("./flash");
    (api.workbenchOutput as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("502: unreachable"));
    (api.workbenchVerifyBoot as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("502: unreachable"));
    const serial: string[] = [];
    const boots: { ok: boolean; error?: string }[] = [];
    await watchSlot("S1", 5, { framework: "lorawan", onBoot: (r) => boots.push(r), onSerial: (t) => serial.push(t), watchSeconds: 5 });
    await new Promise((r) => setTimeout(r, 0));
    expect(serial).toEqual(["\n[slot output unavailable: 502: unreachable]\n"]);
    expect(boots[0]).toMatchObject({ ok: false, error: "502: unreachable" });
  });
});
