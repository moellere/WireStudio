import { describe, expect, it } from "vitest";
import { createSerialProvisioner, macToEui64, type ProvisionValues } from "./provision";

describe("macToEui64", () => {
  it("inserts FFFE into a colon-separated MAC", () => {
    expect(macToEui64("10:52:1c:66:b6:e0")).toBe("10521cfffe66b6e0");
  });
  it("accepts a bare hex MAC and lowercases", () => {
    expect(macToEui64("10521C66B6E0")).toBe("10521cfffe66b6e0");
  });
  it("rejects a wrong-length MAC", () => {
    expect(() => macToEui64("1052")).toThrow(/12-hex/);
  });
});

const VALUES: ProvisionValues = {
  band: "US915",
  sub_band: 2,
  join_eui: "0000000000000000",
  dev_eui: "10521cfffe66b6e0",
  app_key: "00112233445566778899aabbccddeeff",
};

describe("createSerialProvisioner", () => {
  it("answers each LoRaWAN_ESP32 prompt in order", () => {
    const writes: string[] = [];
    const p = createSerialProvisioner(VALUES, (line) => writes.push(line));
    p.feed("Enter LoRaWAN band (e.g. EU868 or US915)  ");
    p.feed("Enter subband for your frequency plan...  ");
    p.feed("Enter joinEUI (64 bits, 16 hex characters.)  ");
    p.feed("Enter devEUI (64 bits, 16 hex characters)  ");
    p.feed("Enter appKey (...)  ");
    p.feed("Enter nwkKey (...)  ");
    expect(writes).toEqual([
      "US915\n",
      "2\n",
      "0000000000000000\n",
      "10521cfffe66b6e0\n",
      "00112233445566778899aabbccddeeff\n",
      "00112233445566778899aabbccddeeff\n",
    ]);
    expect(p.done()).toBe(true);
  });

  it("answers a prompt that was already in the buffer (catch-up)", () => {
    const writes: string[] = [];
    const p = createSerialProvisioner(VALUES, (line) => writes.push(line));
    p.feed("...banner...\nNo provisioning data found.\nEnter LoRaWAN band (e.g. US915)  ");
    expect(writes).toEqual(["US915\n"]);
    expect(p.done()).toBe(false);
  });

  it("sends the AppKey for both appKey and nwkKey (LoRaWAN 1.0.x single root key)", () => {
    const writes: string[] = [];
    const p = createSerialProvisioner(VALUES, (line) => writes.push(line));
    for (const k of ["LoRaWAN band", "subband", "joinEUI", "devEUI", "appKey", "nwkKey"]) {
      p.feed(`Enter ${k}  `);
    }
    expect(writes[4]).toBe(writes[5]);
    expect(writes[5]).toBe("00112233445566778899aabbccddeeff\n");
  });
});
