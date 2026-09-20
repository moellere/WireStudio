import { describe, expect, it, vi } from "vitest";
import {
  defaultSettings, enumOptions, fromBase64, generatePsk, pskProblem, pushMeshtasticConfig, shortNameFor, toBase64,
} from "./meshtastic";

const REGIONS = { UNSET: 0, US: 1, EU_433: 2, EU_868: 3 };

describe("meshtastic settings helpers", () => {
  it("derives names from the design and the region from a LoRaWAN design", () => {
    const s = defaultSettings({ name: "Garage Motion", fleet: { device_name: "garage-motion" }, lorawan: { region: "US915" } }, REGIONS);
    expect(s.longName).toBe("garage-motion");
    expect(s.shortName).toBe("GM");
    expect(s.region).toBe(1);
    expect(s.psk).toBe("");
    expect(defaultSettings(null, REGIONS)).toMatchObject({ longName: "wirestudio node", shortName: "WN", region: 0 });
  });

  it("short names are four characters at most", () => {
    expect(shortNameFor("Bench I/O board")).toBe("BIOB");
    expect(shortNameFor("heltec")).toBe("HELT");
    expect(shortNameFor("")).toBe("NODE");
  });

  it("keys round-trip through base64 and are validated by length", () => {
    const key = generatePsk(16);
    expect(fromBase64(key)).toHaveLength(16);
    expect(fromBase64(generatePsk())).toHaveLength(32);
    expect(toBase64(fromBase64(key))).toBe(key);
    expect(pskProblem("")).toBeNull();
    expect(pskProblem(key)).toBeNull();
    expect(pskProblem(toBase64(new Uint8Array(5)))).toBe("PSK is 5 bytes; a key is 16 or 32");
    expect(pskProblem("not base64!!")).toBe("PSK is not base64");
  });

  it("enum options keep names and sort by value", () => {
    expect(enumOptions({ ...REGIONS, 0: "UNSET", 1: "US" } as Record<string, string | number>)).toEqual([
      ["UNSET", 0], ["US", 1], ["EU_433", 2], ["EU_868", 3],
    ]);
  });
});

describe("pushMeshtasticConfig", () => {
  function fakeClient() {
    const calls: string[] = [];
    const subscribers: Array<(i: { myNodeNum: number }) => void> = [];
    const device = {
      events: { onMyNodeInfo: { subscribe: (fn: (i: { myNodeNum: number }) => void) => subscribers.push(fn) } },
      configure: vi.fn(async () => { calls.push("configure"); subscribers.forEach((fn) => fn({ myNodeNum: 0xabcd })); return 1; }),
      setOwner: vi.fn(async (u: unknown) => { calls.push(`owner:${JSON.stringify(u)}`); return 1; }),
      setConfig: vi.fn(async (c: unknown) => { calls.push(`config:${JSON.stringify(c)}`); return 1; }),
      setChannel: vi.fn(async (c: { settings: { psk: Uint8Array; name: string } }) => { calls.push(`channel:${c.settings.name}:${c.settings.psk.length}`); return 1; }),
      commitEditSettings: vi.fn(async () => { calls.push("commit"); return 1; }),
      disconnect: vi.fn(async () => { calls.push("disconnect"); }),
    };
    const load = async () => ({
      MeshDevice: function FakeDevice() { return device; } as unknown as never,
      TransportWebSerial: { createFromPort: vi.fn(async () => ({})) } as unknown as never,
      create: ((_schema: unknown, init: unknown) => init) as unknown as never,
      Protobuf: {
        Mesh: { UserSchema: "User" },
        Config: {
          ConfigSchema: "Config", Config_LoRaConfigSchema: "LoRa",
          Config_LoRaConfig_RegionCode: { 1: "US" }, Config_LoRaConfig_ModemPreset: { 0: "LONG_FAST" },
        },
        Channel: { ChannelSchema: "Channel", ChannelSettingsSchema: "Settings", Channel_Role: { PRIMARY: 1 } },
      } as unknown as never,
    });
    return { device, calls, load };
  }

  it("handshakes, writes owner, lora and channel, commits, and always disconnects", async () => {
    const { calls, load } = fakeClient();
    const log: string[] = [];
    const node = await pushMeshtasticConfig({} as SerialPort, {
      region: 1, modemPreset: 0, longName: "garage", shortName: "GRG", channelName: "home", psk: generatePsk(32),
    }, (l) => log.push(l), load);
    expect(node).toEqual({ nodeNum: 0xabcd, longName: "garage" });
    expect(calls[0]).toBe("configure");
    expect(calls[1]).toContain('"longName":"garage"');
    expect(calls[2]).toContain('"region":1');
    expect(calls[3]).toBe("channel:home:32");
    expect(calls.slice(4)).toEqual(["commit", "disconnect"]);
    expect(log.some((l) => l.includes("node !abcd answered"))).toBe(true);
    expect(log.some((l) => l.includes("region US, preset LONG_FAST"))).toBe(true);
  });

  it("an empty key keeps the default key byte, and a failure still disconnects", async () => {
    const { device, calls, load } = fakeClient();
    device.setChannel.mockImplementationOnce(async () => { throw new Error("radio busy"); });
    await expect(pushMeshtasticConfig({} as SerialPort, {
      region: 1, modemPreset: 0, longName: "n", shortName: "N", channelName: "", psk: "",
    }, () => {}, load)).rejects.toThrow("radio busy");
    expect(calls.at(-1)).toBe("disconnect");
    const { calls: calls2, load: load2 } = fakeClient();
    await pushMeshtasticConfig({} as SerialPort, {
      region: 1, modemPreset: 0, longName: "n", shortName: "N", channelName: "", psk: "",
    }, () => {}, load2);
    expect(calls2).toContain("channel::1");
  });
});
