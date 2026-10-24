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

const workbenchStream = vi.fn();
vi.mock("../api/client", () => ({
  api: {
    workbenchVerifyBoot: vi.fn(),
  },
  workbenchStream: (...args: unknown[]) => workbenchStream(...args),
}));

async function* events(...items: unknown[]) {
  for (const item of items) {
    if (item instanceof Error) throw item;
    yield item;
  }
}

describe("watchSlot", () => {
  it("relays the stream's lines as they arrive, notes its end, and hands over the boot verdict", async () => {
    const { api } = await import("../api/client");
    const { watchSlot } = await import("./flash");
    workbenchStream.mockReturnValue(events(
      { type: "log", data: "ets Jul 29 2019", ts: 1 },
      { type: "log", data: "setup() finished successfully!\n", ts: 2 },
      { type: "done", ok: true, slot: "S1", reason: "idle" },
    ));
    (api.workbenchVerifyBoot as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, framework: "esphome", booted: true, checks: [] });
    const serial: string[] = [];
    const boots: unknown[] = [];
    await watchSlot("S1", 100, { framework: "esphome", onBoot: (r) => boots.push(r), onSerial: (t) => serial.push(t), watchSeconds: 30 });
    expect(serial).toEqual(["ets Jul 29 2019\n", "setup() finished successfully!\n", "\n[slot relay ended: idle]\n"]);
    expect(boots).toEqual([{ ok: true, framework: "esphome", booted: true, checks: [] }]);
    expect((api.workbenchVerifyBoot as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toEqual({ slot: "S1", framework: "esphome", reset: true });
    expect(workbenchStream.mock.calls[0]).toEqual(["S1", { since: 100, seconds: 30, signal: undefined }]);
  });

  it("reports a failed verify as a result and a refused stream as a line", async () => {
    const { api } = await import("../api/client");
    const { watchSlot } = await import("./flash");
    workbenchStream.mockReturnValue(events(new Error("502: unreachable")));
    (api.workbenchVerifyBoot as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("502: unreachable"));
    const serial: string[] = [];
    const boots: { ok: boolean; error?: string }[] = [];
    await watchSlot("S1", 5, { framework: "lorawan", onBoot: (r) => boots.push(r), onSerial: (t) => serial.push(t), watchSeconds: 5 });
    await new Promise((r) => setTimeout(r, 0));
    expect(serial).toEqual(["\n[slot output unavailable: 502: unreachable]\n"]);
    expect(boots[0]).toMatchObject({ ok: false, error: "502: unreachable" });
  });

  it("goes quiet when the caller aborts the relay", async () => {
    const { watchSlot } = await import("./flash");
    const controller = new AbortController();
    workbenchStream.mockImplementation(async function* () {
      yield { type: "log", data: "one", ts: 1 };
      controller.abort();
      throw new DOMException("The operation was aborted.", "AbortError");
    });
    const serial: string[] = [];
    await watchSlot("S1", 1, { onSerial: (t) => serial.push(t), signal: controller.signal });
    expect(serial).toEqual(["one\n"]);
  });
});
