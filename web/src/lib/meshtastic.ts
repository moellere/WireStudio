/**
 * Meshtastic configuration over serial: region, modem preset, owner and
 * the primary channel, pushed as protobufs through @meshtastic/core once
 * the flash session hands its port over. The PSK is generated or pasted
 * here and goes to the device only; it is never written into the design.
 */
import type { Design } from "../types/api";

export interface MeshtasticSettings {
  /** Protobuf.Config.Config_LoRaConfig_RegionCode value. */
  region: number;
  /** Protobuf.Config.Config_LoRaConfig_ModemPreset value. */
  modemPreset: number;
  longName: string;
  shortName: string;
  channelName: string;
  /** base64 of 16 or 32 bytes; "" keeps the device's default key. */
  psk: string;
}

export interface MeshtasticPushLog {
  (line: string): void;
}

export interface MeshtasticNode {
  nodeNum: number;
  longName: string;
}

/** LoRaWAN region ids the design may carry -> Meshtastic region names. */
const LORAWAN_TO_MESHTASTIC: Record<string, string> = {
  US915: "US",
  EU868: "EU_868",
  AU915: "ANZ",
  AS923: "SG_923",
  KR920: "KR",
  IN865: "IN",
  RU864: "RU",
};

export function defaultSettings(design: Design | null, regions: Record<string, number>): MeshtasticSettings {
  const fleet = (design?.fleet as { device_name?: string } | undefined) ?? {};
  const longName = (fleet.device_name || String(design?.name ?? "") || "wirestudio node").slice(0, 39);
  const lorawan = (design?.lorawan as { region?: string } | undefined)?.region;
  const regionName = (lorawan && LORAWAN_TO_MESHTASTIC[lorawan]) || "UNSET";
  return {
    region: regions[regionName] ?? 0,
    modemPreset: 0,
    longName,
    shortName: shortNameFor(longName),
    channelName: "",
    psk: "",
  };
}

/** Meshtastic short names are at most four characters. */
export function shortNameFor(longName: string): string {
  const words = longName.split(/[^A-Za-z0-9]+/).filter(Boolean);
  const raw = words.length >= 2 ? words.map((w) => w[0]).join("") : (words[0] ?? "");
  return raw.slice(0, 4).toUpperCase() || "NODE";
}

export function generatePsk(bytes: 16 | 32 = 32): string {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return toBase64(buf);
}

export function toBase64(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

export function fromBase64(text: string): Uint8Array {
  const bin = atob(text.trim());
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

/** "" (device default), or a 16 / 32 byte key; anything else is a typo. */
export function pskProblem(psk: string): string | null {
  if (!psk.trim()) return null;
  try {
    const n = fromBase64(psk).length;
    return n === 16 || n === 32 ? null : `PSK is ${n} bytes; a key is 16 or 32`;
  } catch {
    return "PSK is not base64";
  }
}

/** Enum objects from the protobufs are numeric on both sides; keep the names. */
export function enumOptions(e: Record<string, string | number>): Array<[string, number]> {
  return Object.entries(e)
    .filter((kv): kv is [string, number] => typeof kv[1] === "number")
    .sort((a, b) => a[1] - b[1]);
}

export async function loadMeshtastic() {
  const [{ MeshDevice, Protobuf }, { TransportWebSerial }, { create }] = await Promise.all([
    import("@meshtastic/core"),
    import("@meshtastic/transport-web-serial"),
    import("@bufbuild/protobuf"),
  ]);
  return { MeshDevice, Protobuf, TransportWebSerial, create };
}

type Loaded = Awaited<ReturnType<typeof loadMeshtastic>>;

/**
 * Push `settings` to the device on `port`. Waits for the node to answer
 * the config handshake, writes owner, LoRa config and the primary
 * channel, then commits; a region change makes the device reboot, which
 * is the last line the log shows.
 */
export async function pushMeshtasticConfig(
  port: SerialPort,
  settings: MeshtasticSettings,
  log: MeshtasticPushLog,
  load: () => Promise<Loaded> = loadMeshtastic,
): Promise<MeshtasticNode> {
  const { MeshDevice, Protobuf, TransportWebSerial, create } = await load();
  const transport = await TransportWebSerial.createFromPort(port, 115200);
  const device = new MeshDevice(transport);
  const nodeInfo = new Promise<{ myNodeNum: number }>((resolve) => {
    device.events.onMyNodeInfo.subscribe((info: { myNodeNum: number }) => resolve(info));
  });
  try {
    log("connecting to the node…");
    await device.configure();
    const info = await withTimeout(nodeInfo, 20000, "the node did not answer the config handshake");
    log(`node !${info.myNodeNum.toString(16)} answered`);

    await device.setOwner(create(Protobuf.Mesh.UserSchema, {
      longName: settings.longName,
      shortName: settings.shortName,
    }));
    log(`owner set: ${settings.longName} (${settings.shortName})`);

    const lora = create(Protobuf.Config.Config_LoRaConfigSchema, {
      usePreset: true,
      modemPreset: settings.modemPreset,
      region: settings.region,
      txEnabled: true,
      hopLimit: 3,
    });
    await device.setConfig(create(Protobuf.Config.ConfigSchema, {
      payloadVariant: { case: "lora", value: lora },
    }));
    log(`LoRa: region ${Protobuf.Config.Config_LoRaConfig_RegionCode[settings.region]}, preset ${Protobuf.Config.Config_LoRaConfig_ModemPreset[settings.modemPreset]}`);

    const psk = settings.psk.trim() ? fromBase64(settings.psk) : new Uint8Array([1]);
    await device.setChannel(create(Protobuf.Channel.ChannelSchema, {
      index: 0,
      role: Protobuf.Channel.Channel_Role.PRIMARY,
      settings: create(Protobuf.Channel.ChannelSettingsSchema, {
        name: settings.channelName,
        psk,
      }),
    }));
    log(`primary channel: ${settings.channelName || "(default name)"}, ${settings.psk.trim() ? `${psk.length}-byte key` : "default key"}`);

    await device.commitEditSettings();
    log("committed; the node reboots to apply the region");
    return { nodeNum: info.myNodeNum, longName: settings.longName };
  } finally {
    try {
      await device.disconnect();
    } catch {
      // the node may already be rebooting
    }
  }
}

function withTimeout<T>(p: Promise<T>, ms: number, what: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error(what)), ms);
    p.then((v) => { clearTimeout(t); resolve(v); }, (e) => { clearTimeout(t); reject(e); });
  });
}
