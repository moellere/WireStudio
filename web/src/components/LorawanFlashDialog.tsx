import { useEffect, useRef, useState } from "react";
import type { BoardSummary, Design } from "../types/api";
import { api, lorawanCompile } from "../api/client";
import { isWebSerialSupported } from "../lib/usb-detect";
import { APP_PARTITION_OFFSET, flashFirmware, type FlashSession } from "../lib/flash";
import { createSerialProvisioner, macToEui64 } from "../lib/provision";

type Phase =
  | "loading"
  | "idle"
  | "building"
  | "built"
  | "flashing"
  | "monitoring"
  | "error";

interface Props {
  onClose: () => void;
}

interface GpsCfg {
  rx_pin: string;
  tx_pin: string;
  baud: number;
}

/** Minimal lorawan design for a radio board: target + lorawan block (US915
 *  sub-band 2 defaults apply). External GPS / DHT22 / OLED (for boards without
 *  them onboard) go in lorawan.*. Credentials arrive via serial provisioning. */
function lorawanDesign(
  board: BoardSummary,
  opts: { gps?: GpsCfg; dht22?: { pin: string }; oled?: boolean } = {},
): Design {
  const lorawan: Record<string, unknown> = {};
  if (opts.gps) lorawan.gps = opts.gps;
  if (opts.dht22) lorawan.dht22 = opts.dht22;
  if (opts.oled) lorawan.oled = {};
  return {
    schema_version: "0.1",
    id: board.id,
    name: board.name,
    target: "lorawan",
    lorawan,
    board: { library_id: board.id, mcu: board.mcu, framework: board.framework },
    power: { supply: "usb-5v", rail_voltage_v: 5.0, budget_ma: 500 },
    requirements: [],
    components: [],
    buses: [],
    connections: [],
    passives: [],
    warnings: [],
  };
}

function tail(parts: string[], max = 200): string[] {
  return parts.length > max ? parts.slice(parts.length - max) : parts;
}

export function LorawanFlashDialog({ onClose }: Props) {
  const supported = isWebSerialSupported();
  const [phase, setPhase] = useState<Phase>("loading");
  const [boards, setBoards] = useState<BoardSummary[] | null>(null);
  const [boardId, setBoardId] = useState("");
  const [buildLog, setBuildLog] = useState<string[]>([]);
  const [cacheKey, setCacheKey] = useState<string | null>(null);
  const [flashLog, setFlashLog] = useState<string[]>([]);
  const [progress, setProgress] = useState<{ written: number; total: number } | null>(null);
  const [serial, setSerial] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  const [devEui, setDevEui] = useState<string | null>(null);
  const [provisionStatus, setProvisionStatus] = useState<string | null>(null);
  const [gpsEnabled, setGpsEnabled] = useState(false);
  // NOT GPIO3/1: those are U0RXD/U0TXD (the USB-serial console) on the classic
  // ESP32 -- a GPS there floods the provisioning prompt with garbage. 23/17 are
  // free + output-capable on these boards.
  const [gpsRx, setGpsRx] = useState("GPIO23"); // MCU RX  <- GPS module TX
  const [gpsTx, setGpsTx] = useState("GPIO17"); // MCU TX  -> GPS module RX
  const [gpsBaud, setGpsBaud] = useState(9600);
  const [dhtEnabled, setDhtEnabled] = useState(false);
  const [dhtPin, setDhtPin] = useState("GPIO13");
  const [oledEnabled, setOledEnabled] = useState(false);
  const [offlineTest, setOfflineTest] = useState(false);
  const [fullFlash, setFullFlash] = useState(false);
  const sessionRef = useRef<FlashSession | null>(null);

  function buildDesign(): Design | null {
    const board = boards?.find((b) => b.id === boardId);
    if (!board) return null;
    return lorawanDesign(board, {
      gps: gpsEnabled ? { rx_pin: gpsRx, tx_pin: gpsTx, baud: gpsBaud } : undefined,
      dht22: dhtEnabled ? { pin: dhtPin } : undefined,
      oled: oledEnabled,
    });
  }

  const serialBufRef = useRef("");
  const provisionerRef = useRef<ReturnType<typeof createSerialProvisioner> | null>(null);
  const provisionTriggeredRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    api
      .listBoardsForTarget("lorawan")
      .then((bs) => {
        if (cancelled) return;
        setBoards(bs);
        setBoardId(bs[0]?.id ?? "");
        setPhase("idle");
      })
      .catch((e) => {
        if (cancelled) return;
        setErrorMsg(e instanceof Error ? e.message : String(e));
        setPhase("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Release the serial port if the dialog closes mid-monitor.
  useEffect(() => {
    return () => {
      sessionRef.current?.close().catch(() => {});
    };
  }, []);

  async function handleBuild() {
    const design = buildDesign();
    if (!design) return;
    setPhase("building");
    setBuildLog([]);
    setCacheKey(null);
    try {
      for await (const event of lorawanCompile(design)) {
        if (event.type === "log") {
          setBuildLog((prev) => tail([...prev, ...event.data.split("\n")]));
        } else if (event.type === "done") {
          if (event.ok) {
            setCacheKey(event.cache_key);
            setPhase("built");
          } else {
            setErrorMsg("firmware build failed; see the build log");
            setPhase("error");
          }
        }
      }
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }

  async function handleFlash() {
    if (!cacheKey) return;
    setPhase("flashing");
    setFlashLog([]);
    setSerial("");
    setProgress(null);
    setDevEui(null);
    setProvisionStatus(null);
    serialBufRef.current = "";
    provisionerRef.current = null;
    provisionTriggeredRef.current = false;
    try {
      // Blank board: a merged factory image (bootloader+partitions+app) flashed
      // at 0x0 with a full erase. Otherwise an app-region re-flash that keeps the
      // bootloader + NVS (DevNonces). Provisioning after a full flash re-flushes
      // nonces, so the wiped NVS is fine.
      const images = fullFlash
        ? [{ data: await api.lorawanFactory(cacheKey), address: 0x0 }]
        : [{ data: await api.lorawanFirmware(cacheKey), address: APP_PARTITION_OFFSET }];
      const session = await flashFirmware({
        images,
        eraseAll: fullFlash,
        onProgress: (written, total) => setProgress({ written, total }),
        onLog: (line) => setFlashLog((prev) => tail([...prev, line])),
        onSerial: (text) => {
          serialBufRef.current += text;
          setSerial((prev) => (prev + text).slice(-8000));
          provisionerRef.current?.feed(text);
          maybeTriggerProvision();
        },
      });
      sessionRef.current = session;
      setPhase("monitoring");
      maybeTriggerProvision(); // in case the prompt already landed during flash
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }

  // Provision only when the device actually asks (empty NVS). A re-flash
  // preserves NVS, so an already-provisioned device boots straight to JOIN with
  // its stored keys -- re-provisioning then would re-key ChirpStack and break
  // that join. So we watch the serial stream and act on what the device says.
  function maybeTriggerProvision() {
    if (provisionTriggeredRef.current) return;
    const session = sessionRef.current;
    if (!session) return; // session not set yet; a later serial chunk re-checks
    const buf = serialBufRef.current;
    if (/No provisioning data found|Enter LoRaWAN band/i.test(buf)) {
      provisionTriggeredRef.current = true;
      void autoProvision(session);
    } else if (/JOINED|OTAA session active/i.test(buf)) {
      provisionTriggeredRef.current = true;
      if (session.mac) {
        const eui = macToEui64(session.mac);
        setDevEui(eui);
        setProvisionStatus("already provisioned (NVS) — syncing codec…");
        void syncCodec(eui, "already provisioned — codec synced; uplinks decode in ChirpStack");
      } else {
        setProvisionStatus("device already provisioned (NVS) — joined with its stored keys");
      }
    }
  }

  // Set the board's decodeUplink codec on the device's ChirpStack profile so
  // uplinks decode into named fields. Best-effort; the join already works.
  async function syncCodec(eui: string, okStatus: string) {
    const design = buildDesign();
    if (!design) return;
    try {
      await api.lorawanSetCodec({ dev_eui: eui, design });
      setProvisionStatus(okStatus);
    } catch (e) {
      setProvisionStatus(`codec sync failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  // Register the device in ChirpStack and feed a driver that answers the
  // firmware's serial prompts. Failures here are non-fatal: the monitor still
  // works for manual entry, so they surface as a status, not an error phase.
  async function autoProvision(session: FlashSession) {
    if (!session.mac) {
      setProvisionStatus("no MAC read from chip — answer the prompts manually below");
      return;
    }
    const design = buildDesign();
    if (!design) return;
    try {
      const eui = macToEui64(session.mac);
      setDevEui(eui);
      // Offline test: answer the prompt with throwaway keys (no ChirpStack) so
      // the device clears provisioning and runs the sensor/OLED loop. It won't
      // actually join (bogus keys), which is fine when there's no gateway.
      let values: { band: string; sub_band: number; join_eui: string; dev_eui: string; app_key: string };
      if (offlineTest) {
        setProvisionStatus("offline test — writing throwaway keys (sensors run, no real join)");
        values = {
          band: "US915", sub_band: 2,
          join_eui: "0000000000000000", dev_eui: eui,
          app_key: "00000000000000000000000000000000",
        };
      } else {
        setProvisionStatus("registering in ChirpStack…");
        values = await api.lorawanProvision({ dev_eui: eui, design });
      }
      const provisioner = createSerialProvisioner(
        {
          band: values.band,
          sub_band: values.sub_band,
          join_eui: values.join_eui,
          dev_eui: values.dev_eui,
          app_key: values.app_key,
        },
        (line) => void session.write(line).catch(() => {}),
        (i, total) =>
          setProvisionStatus(
            i < total
              ? `answering prompts (${i}/${total})…`
              : offlineTest
                ? "throwaway keys written — sensors/OLED live, no real join"
                : "provisioned — waiting for join…",
          ),
      );
      provisionerRef.current = provisioner;
      provisioner.feed(serialBufRef.current); // catch a prompt already printed before now
      if (!offlineTest) await syncCodec(eui, "provisioned + codec set — waiting for join…");
    } catch (e) {
      setProvisionStatus(`provisioning failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function handleStop() {
    await sessionRef.current?.close().catch(() => {});
    sessionRef.current = null;
    setPhase("built");
  }

  // Tell the device to clear stored keys (e.g. throwaway offline-test keys) and
  // reboot, so it re-prompts for real provisioning. Needs the "wipe" handler in
  // the firmware loop, so it only reaches a device that got past provisioning.
  async function handleWipe() {
    await sessionRef.current?.write("wipe\n").catch(() => {});
    setProvisionStatus("sent wipe — device clearing keys + rebooting; it will re-prompt to provision");
  }

  const pct = progress && progress.total > 0
    ? Math.round((progress.written / progress.total) * 100)
    : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="m-4 max-h-[85vh] w-full max-w-2xl overflow-auto rounded-lg border border-zinc-800 bg-zinc-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-zinc-100">Flash LoRaWAN firmware</div>
            <div className="text-xs text-zinc-500">
              Build a radio board&apos;s firmware server-side, flash it over WebSerial, watch the join.
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-900"
          >
            Close
          </button>
        </div>

        <div className="space-y-4 p-4 text-sm">
          {supported === "no" && <UnsupportedNotice />}

          {phase === "loading" && <div className="text-xs text-zinc-500">Loading radio boards…</div>}

          {(phase === "idle" || phase === "building" || phase === "built") && boards && (
            <BoardPicker
              boards={boards}
              boardId={boardId}
              onPick={setBoardId}
              disabled={phase === "building"}
            />
          )}

          {(phase === "idle" || phase === "building" || phase === "built") && (
            <section>
              <label className="flex items-center gap-2 text-xs text-zinc-300">
                <input
                  type="checkbox"
                  checked={gpsEnabled}
                  disabled={phase === "building"}
                  onChange={(e) => setGpsEnabled(e.target.checked)}
                  className="h-3.5 w-3.5"
                />
                Attach an external GPS module (UART)
              </label>
              {gpsEnabled && (
                <div className="mt-2 grid grid-cols-3 gap-2">
                  <PinField label="MCU RX (← GPS TX)" value={gpsRx} onChange={setGpsRx} disabled={phase === "building"} />
                  <PinField label="MCU TX (→ GPS RX)" value={gpsTx} onChange={setGpsTx} disabled={phase === "building"} />
                  <label className="text-[11px] text-zinc-500">
                    Baud
                    <input
                      type="number"
                      value={gpsBaud}
                      disabled={phase === "building"}
                      onChange={(e) => setGpsBaud(Number(e.target.value) || 9600)}
                      className="mt-0.5 w-full rounded border border-zinc-800 bg-zinc-900 px-1.5 py-1 font-mono text-xs text-zinc-200"
                    />
                  </label>
                </div>
              )}
              {gpsEnabled && (
                <p className="mt-1 text-[11px] text-zinc-600">
                  For boards without an onboard GPS. Ignored if the board already has one.
                  Avoid GPIO1/GPIO3 on a classic ESP32 — they&apos;re the USB-serial console,
                  and a GPS there floods the provisioning prompt.
                </p>
              )}

              <label className="mt-2 flex items-center gap-2 text-xs text-zinc-300">
                <input
                  type="checkbox"
                  checked={dhtEnabled}
                  disabled={phase === "building"}
                  onChange={(e) => setDhtEnabled(e.target.checked)}
                  className="h-3.5 w-3.5"
                />
                Attach a DHT22 (temperature + humidity)
              </label>
              {dhtEnabled && (
                <div className="mt-1 w-32">
                  <PinField label="Data pin" value={dhtPin} onChange={setDhtPin} disabled={phase === "building"} />
                </div>
              )}

              <label className="mt-2 flex items-center gap-2 text-xs text-zinc-300">
                <input
                  type="checkbox"
                  checked={oledEnabled}
                  disabled={phase === "building"}
                  onChange={(e) => setOledEnabled(e.target.checked)}
                  className="h-3.5 w-3.5"
                />
                Show telemetry on an SSD1306 OLED (lat/lon/batt/temp)
              </label>

              <label className="mt-2 flex items-center gap-2 text-xs text-amber-300">
                <input
                  type="checkbox"
                  checked={offlineTest}
                  disabled={phase === "building"}
                  onChange={(e) => setOfflineTest(e.target.checked)}
                  className="h-3.5 w-3.5"
                />
                Offline test — skip ChirpStack, write throwaway keys
              </label>
              {offlineTest && (
                <p className="mt-1 text-[11px] text-zinc-600">
                  Clears the provisioning prompt without a gateway so the device runs its
                  sensor/OLED loop. It won&apos;t actually join. Re-flash without this for real use.
                </p>
              )}

              <label className="mt-2 flex items-center gap-2 text-xs text-zinc-300">
                <input
                  type="checkbox"
                  checked={fullFlash}
                  disabled={phase === "building"}
                  onChange={(e) => setFullFlash(e.target.checked)}
                  className="h-3.5 w-3.5"
                />
                Blank board — full flash (bootloader + partitions + app)
              </label>
              {fullFlash && (
                <p className="mt-1 text-[11px] text-zinc-600">
                  Full-chip erase + a merged factory image at 0x0, for a board that has
                  never been flashed. Wipes NVS; leave off to re-flash a board that already
                  boots (preserves the bootloader + stored keys).
                </p>
              )}
            </section>
          )}

          {(phase === "building" || phase === "built") && (
            <section>
              <Heading>Build</Heading>
              <LogBox log={buildLog} />
              {phase === "built" && cacheKey && (
                <div className="mt-1 text-xs text-emerald-300">
                  firmware ready (key {cacheKey})
                </div>
              )}
            </section>
          )}

          {(phase === "flashing" || phase === "monitoring") && (
            <section className="space-y-2">
              <Heading>Flash</Heading>
              {pct !== null && (
                <div className="h-2 w-full overflow-hidden rounded bg-zinc-800">
                  <div className="h-full bg-blue-500 transition-all" style={{ width: `${pct}%` }} />
                </div>
              )}
              <LogBox log={flashLog} />
            </section>
          )}

          {phase === "monitoring" && (devEui || provisionStatus) && (
            <section className="space-y-1">
              <Heading>Provisioning</Heading>
              <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-2 text-xs">
                {devEui && (
                  <div>
                    DevEUI <span className="font-mono text-zinc-300">{devEui}</span>
                  </div>
                )}
                {provisionStatus && <div className="mt-0.5 text-zinc-400">{provisionStatus}</div>}
              </div>
            </section>
          )}

          {(phase === "monitoring" || (phase === "built" && serial)) && (
            <section className="space-y-1">
              <Heading>Serial monitor</Heading>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md border border-zinc-800 bg-zinc-900/50 p-2 font-mono text-[11px] text-emerald-200/90">
                {serial || "(waiting for device output…)"}
              </pre>
            </section>
          )}

          {phase === "error" && (
            <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-200">
              <div className="font-semibold">Something went wrong</div>
              <div className="mt-1 whitespace-pre-wrap">{errorMsg}</div>
              {buildLog.length > 0 && <LogBox log={buildLog} className="mt-2" />}
            </div>
          )}

          <div className="flex justify-end gap-2 border-t border-zinc-800 pt-3">
            {(phase === "idle" || phase === "built" || phase === "error") && (
              <button
                disabled={supported === "no" || !boardId}
                onClick={handleBuild}
                className="rounded-md border border-zinc-800 px-3 py-1.5 text-xs text-zinc-200 enabled:hover:bg-zinc-900 disabled:opacity-40"
              >
                {phase === "built" ? "Rebuild" : "Build firmware"}
              </button>
            )}
            {phase === "built" && (
              <button
                disabled={supported === "no" || !cacheKey}
                onClick={handleFlash}
                className="rounded-md bg-blue-500/20 px-3 py-1.5 text-xs text-blue-100 ring-1 ring-blue-400/40 enabled:hover:bg-blue-500/30 disabled:opacity-40"
              >
                Flash &amp; monitor →
              </button>
            )}
            {phase === "monitoring" && (
              <button
                onClick={handleWipe}
                title="Clear stored LoRaWAN keys (e.g. throwaway offline-test keys) and reboot to re-provision"
                className="rounded-md border border-amber-500/40 px-3 py-1.5 text-xs text-amber-200 hover:bg-amber-500/10"
              >
                Wipe keys
              </button>
            )}
            {phase === "monitoring" && (
              <button
                onClick={handleStop}
                className="rounded-md border border-zinc-800 px-3 py-1.5 text-xs text-zinc-200 hover:bg-zinc-900"
              >
                Stop monitor
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function PinField({
  label, value, onChange, disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
}) {
  return (
    <label className="text-[11px] text-zinc-500">
      {label}
      <input
        type="text"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="mt-0.5 w-full rounded border border-zinc-800 bg-zinc-900 px-1.5 py-1 font-mono text-xs text-zinc-200"
      />
    </label>
  );
}

function BoardPicker({
  boards, boardId, onPick, disabled,
}: {
  boards: BoardSummary[];
  boardId: string;
  onPick: (id: string) => void;
  disabled: boolean;
}) {
  return (
    <div>
      <Heading>Radio board</Heading>
      <ul className="space-y-1">
        {boards.map((b) => (
          <li key={b.id}>
            <label className="flex cursor-pointer items-center gap-2 rounded-md border border-zinc-800 bg-zinc-900/40 px-2 py-1.5 hover:bg-zinc-900">
              <input
                type="radio"
                name="lorawan-board"
                value={b.id}
                checked={boardId === b.id}
                disabled={disabled}
                onChange={() => onPick(b.id)}
                className="h-3.5 w-3.5"
              />
              <span className="flex-1 text-xs">
                <span className="text-zinc-100">{b.name}</span>
                <span className="ml-2 text-zinc-500">{b.chip_variant}</span>
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}

function UnsupportedNotice() {
  return (
    <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-100">
      <div className="mb-1 font-semibold">WebSerial isn&apos;t available here.</div>
      <div>
        Flashing needs a Chromium browser (Chrome, Edge, Brave; not Firefox/Safari)
        <b> and</b> a secure context. On Chrome this usually means the page isn&apos;t
        secure: open it over <code>https://</code> or <code>http://localhost</code> (e.g. an
        SSH tunnel) — a plain <code>http://&lt;ip&gt;</code> LAN address disables WebSerial.
      </div>
    </div>
  );
}

function Heading({ children }: { children: React.ReactNode }) {
  return <div className="mb-2 text-xs uppercase tracking-wide text-zinc-500">{children}</div>;
}

function LogBox({ log, className = "" }: { log: string[]; className?: string }) {
  return (
    <pre
      className={`max-h-40 overflow-auto rounded-md border border-zinc-800 bg-zinc-900/50 p-2 font-mono text-[11px] text-zinc-400 ${className}`}
    >
      {log.join("\n")}
    </pre>
  );
}
