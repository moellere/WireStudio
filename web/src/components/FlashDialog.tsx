import { useEffect, useMemo, useRef, useState } from "react";
import { Radio, UploadCloud, Zap } from "lucide-react";
import type { BoardSummary, Design, WorkbenchSlot, WorkbenchStatus } from "../types/api";
import { api, ApiError } from "../api/client";
import { flashToTarget, type FlashSession, type FlashTarget } from "../lib/flash";
import { tasmotaConfigCommands, type TasmotaTemplate } from "../lib/tasmota";
import { Button, Dialog, FieldLabel, Input } from "./ui";
import { LorawanFlashDialog } from "./LorawanFlashDialog";

type Framework = "esphome" | "tasmota" | "lorawan" | "meshtastic" | "circuitpython";

const FRAMEWORKS: Array<{ id: Framework; label: string; note: string; disabled?: boolean }> = [
  { id: "esphome", label: "ESPHome", note: "OTA via fleet-for-esphome; no serial flash needed" },
  { id: "tasmota", label: "Tasmota", note: "official release image + template push over serial" },
  { id: "lorawan", label: "LoRaWAN", note: "compile RadioLib firmware, flash, provision" },
  { id: "meshtastic", label: "Meshtastic", note: "official release image; configure via client.meshtastic.org" },
  { id: "circuitpython", label: "CircuitPython", note: "official release image + starter code.py for the CIRCUITPY drive" },
];

interface Props {
  design: Design | null;
  boards: BoardSummary[] | null;
  onClose: () => void;
  onOpenFleet: () => void;
}

/**
 * Local USB vs a remote bench slot. Renders nothing until the workbench
 * status probe answers, and nothing at all when no bench is configured --
 * a lone "Local USB" toggle is noise for the majority who have none.
 */
function FlashTargetPicker({
  target,
  onChange,
  disabled,
}: {
  target: FlashTarget;
  onChange: (t: FlashTarget) => void;
  disabled: boolean;
}) {
  const [status, setStatus] = useState<WorkbenchStatus | null>(null);
  const [slots, setSlots] = useState<WorkbenchSlot[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.workbenchStatus()
      .then((s) => {
        if (cancelled) return;
        setStatus(s);
        if (!s.available) return;
        return api.workbenchSlots()
          .then((r) => { if (!cancelled) setSlots(r.slots); })
          .catch(() => { if (!cancelled) setSlots([]); });
      })
      .catch(() => {
        if (!cancelled) setStatus({ available: false, reason: null, url: null, configure_hint: null });
      });
    return () => { cancelled = true; };
  }, []);

  if (!status?.available) return null;

  const usable = (slots ?? []).filter((s) => s.flashable);

  return (
    <div className="space-y-2 rounded-lg border border-line bg-surface-2/40 p-3">
      <FieldLabel>Flash target</FieldLabel>
      <div className="grid grid-cols-2 gap-2">
        <button
          disabled={disabled}
          onClick={() => onChange({ kind: "usb" })}
          className={`rounded-lg border px-3 py-2 text-left transition-colors disabled:opacity-40 ${
            target.kind === "usb"
              ? "border-accent-500/50 bg-accent-500/5"
              : "border-line bg-surface-2/40 enabled:hover:border-line-strong"
          }`}
        >
          <div className="text-sm font-medium text-ink">Local USB</div>
          <div className="mt-0.5 text-[11px] text-ink-faint">WebSerial, board plugged into this machine</div>
        </button>
        <button
          disabled={disabled || usable.length === 0}
          onClick={() => usable[0] && onChange({ kind: "workbench", slot: usable[0].label })}
          className={`rounded-lg border px-3 py-2 text-left transition-colors disabled:opacity-40 ${
            target.kind === "workbench"
              ? "border-accent-500/50 bg-accent-500/5"
              : "border-line bg-surface-2/40 enabled:hover:border-line-strong"
          }`}
        >
          <div className="text-sm font-medium text-ink">Workbench slot</div>
          <div className="mt-0.5 text-[11px] text-ink-faint">
            {slots === null
              ? "checking slots…"
              : usable.length === 0
                ? "no slot ready"
                : `${usable.length} slot${usable.length > 1 ? "s" : ""} ready`}
          </div>
        </button>
      </div>

      {target.kind === "workbench" && (
        <div className="flex flex-wrap gap-1.5">
          {(slots ?? []).map((s) => (
            <button
              key={s.label}
              disabled={disabled || !s.flashable}
              title={s.blocked_reason ?? s.product ?? undefined}
              onClick={() => onChange({ kind: "workbench", slot: s.label })}
              className={`rounded-md border px-2 py-1 font-mono text-[11px] transition-colors disabled:opacity-40 ${
                target.slot === s.label
                  ? "border-accent-500/50 bg-accent-500/10 text-ink"
                  : "border-line bg-surface-2/40 text-ink-dim enabled:hover:border-line-strong"
              }`}
            >
              {s.label}
              {!s.flashable && <span className="ml-1 text-ink-faint">·{s.state}</span>}
            </button>
          ))}
        </div>
      )}

      {target.kind === "workbench" && (
        <p className="text-[11px] text-ink-faint">
          The bench runs esptool on its own USB and reports when the flash
          finishes, so the log arrives at the end rather than live.
        </p>
      )}
    </div>
  );
}

/** One flashing surface for every framework. WebSerial + esptool-js is
 *  the single mechanism; frameworks differ only in where the image
 *  comes from and what gets pushed over serial afterwards. */
export function FlashDialog({ design, boards, onClose, onOpenFleet }: Props) {
  const [framework, setFramework] = useState<Framework>("tasmota");

  if (framework === "lorawan") {
    return <LorawanFlashDialog onClose={onClose} />;
  }

  return (
    <Dialog
      title="Flash device"
      subtitle="Pick the firmware framework; flashing always runs over WebSerial."
      onClose={onClose}
      maxWidth="max-w-2xl"
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2">
          {FRAMEWORKS.map((f) => (
            <button
              key={f.id}
              disabled={f.disabled}
              onClick={() => setFramework(f.id)}
              className={`rounded-lg border px-3 py-2 text-left transition-colors disabled:opacity-40 ${
                framework === f.id
                  ? "border-accent-500/50 bg-accent-500/5"
                  : "border-line bg-surface-2/40 enabled:hover:border-line-strong enabled:hover:bg-surface-2"
              }`}
            >
              <div className="text-sm font-medium text-ink">{f.label}</div>
              <div className="mt-0.5 text-[11px] text-ink-faint">{f.note}</div>
            </button>
          ))}
        </div>

        {framework === "esphome" && (
          <div className="space-y-3 rounded-lg border border-line bg-surface-2/40 p-3 text-xs text-ink-dim">
            <p>
              ESPHome devices build and deploy over the air through the
              fleet-for-esphome pipeline — push the rendered YAML and the
              fleet compiles and updates the device; no serial connection
              needed after first provisioning.
            </p>
            <Button variant="primary" onClick={() => { onClose(); onOpenFleet(); }}>
              <UploadCloud className="h-3.5 w-3.5" />
              Push to fleet
            </Button>
          </div>
        )}

        {framework === "tasmota" && (
          <TasmotaFlash design={design} boards={boards} />
        )}

        {framework === "meshtastic" && (
          <MeshtasticFlash design={design} boards={boards} />
        )}

        {framework === "circuitpython" && (
          <CircuitPythonFlash design={design} boards={boards} />
        )}
      </div>
    </Dialog>
  );
}

type MeshtasticPhase = "idle" | "fetching" | "flashing" | "flashed";

function MeshtasticFlash({ design, boards }: { design: Design | null; boards: BoardSummary[] | null }) {
  const [status, setStatus] = useState<{
    available: boolean;
    version: string | null;
    boards: string[];
    reason: string | null;
  } | null>(null);
  const [phase, setPhase] = useState<MeshtasticPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number>(0);
  const [log, setLog] = useState<string[]>([]);
  const [serial, setSerial] = useState<string>("");
  const [target, setTarget] = useState<FlashTarget>({ kind: "usb" });
  const sessionRef = useRef<FlashSession | null>(null);

  const boardLibraryId = String((design?.board as Record<string, unknown> | undefined)?.library_id ?? "");
  const board = useMemo(
    () => (boards ?? []).find((b) => b.id === boardLibraryId) ?? null,
    [boards, boardLibraryId],
  );
  const supported = status?.boards.includes(boardLibraryId) ?? false;

  useEffect(() => {
    let cancelled = false;
    api.meshtasticFirmwareStatus()
      .then((s) => { if (!cancelled) setStatus(s); })
      .catch((e) => {
        if (!cancelled) {
          setStatus({ available: false, version: null, boards: [], reason: e instanceof Error ? e.message : String(e) });
        }
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => () => { void sessionRef.current?.close(); }, []);

  function appendLog(line: string) {
    setLog((l) => [...l.slice(-200), line]);
  }

  async function handleFlash() {
    setError(null);
    setPhase("fetching");
    try {
      const { data, offset } = await api.meshtasticFirmware(boardLibraryId);
      appendLog(`fetched ${status?.version ?? "release"} factory image (${(data.length / 1024).toFixed(0)} KiB)`);
      setPhase("flashing");
      const session = await flashToTarget(target, {
        images: [{ data, address: offset }],
        eraseAll: true,
        chip: board?.chip_variant,
        onProgress: (written, total) => setProgress(total ? written / total : 0),
        onLog: appendLog,
        onSerial: (text) => setSerial((s) => (s + text).slice(-8000)),
      });
      sessionRef.current = session;
      setPhase("flashed");
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : e instanceof Error ? e.message : String(e));
      setPhase("idle");
    }
  }

  return (
    <div className="space-y-3">
      {status !== null && !status.available && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">
          <div className="font-semibold">Firmware download unavailable</div>
          <div className="mt-1">{status.reason}</div>
        </div>
      )}

      <FlashTargetPicker
        target={target}
        onChange={setTarget}
        disabled={phase === "fetching" || phase === "flashing"}
      />

      <div className="flex items-center justify-between gap-3 text-xs text-ink-dim">
        <div>
          {!design
            ? "Open a design with a supported radio board (Heltec V2/V3/V4, T-Beam, TTGO LoRa32)."
            : supported
              ? <>Flashing the official Meshtastic {status?.version ?? "release"} factory image for <code className="font-mono text-ink">{board?.name ?? boardLibraryId}</code>, full-chip erase.</>
              : <>No Meshtastic firmware mapping for <code className="font-mono text-ink">{board?.name ?? boardLibraryId}</code>. Supported: Heltec V2/V3/V4, T-Beam, TTGO LoRa32.</>}
        </div>
        <Button
          variant="primary"
          disabled={!supported || !status?.available || phase === "fetching" || phase === "flashing"}
          onClick={handleFlash}
        >
          <Zap className="h-3.5 w-3.5" />
          {phase === "fetching" ? "Fetching…" : phase === "flashing" ? `Flashing ${(progress * 100).toFixed(0)}%` : "Flash Meshtastic"}
        </Button>
      </div>

      {log.length > 0 && (
        <pre className="max-h-32 overflow-auto rounded-lg bg-surface-0 p-2 font-mono text-[11px] leading-snug text-ink-dim ring-1 ring-line">
          {log.join("\n")}
        </pre>
      )}

      {phase === "flashed" && (
        <div className="rounded-lg border border-line bg-surface-2/40 p-3 text-xs text-ink-dim">
          Device flashed. Meshtastic configuration (region, channels) is
          protobuf over serial, not console commands — set it up in the
          official client at{" "}
          <a
            href="https://client.meshtastic.org"
            target="_blank"
            rel="noreferrer"
            className="text-accent-400 underline decoration-accent-500/40 hover:text-accent-300"
          >
            client.meshtastic.org
          </a>{" "}
          (Serial connection) after closing this dialog to free the port.
        </div>
      )}

      {serial && (
        <pre className="max-h-40 overflow-auto rounded-lg bg-surface-0 p-2 font-mono text-[11px] leading-snug text-emerald-300/90 ring-1 ring-line">
          {serial}
        </pre>
      )}

      {error && (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-200 whitespace-pre-wrap">
          {error}
        </div>
      )}
    </div>
  );
}

type CircuitPythonPhase = "idle" | "fetching" | "flashing" | "flashed";

function CircuitPythonFlash({ design, boards }: { design: Design | null; boards: BoardSummary[] | null }) {
  const [status, setStatus] = useState<{
    available: boolean;
    version: string | null;
    boards: string[];
    generic: string[];
    images: Record<string, string>;
    reason: string | null;
  } | null>(null);
  const [phase, setPhase] = useState<CircuitPythonPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number>(0);
  const [log, setLog] = useState<string[]>([]);
  const [serial, setSerial] = useState<string>("");
  const [starter, setStarter] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [target, setTarget] = useState<FlashTarget>({ kind: "usb" });
  const sessionRef = useRef<FlashSession | null>(null);

  const boardLibraryId = String((design?.board as Record<string, unknown> | undefined)?.library_id ?? "");
  const board = useMemo(
    () => (boards ?? []).find((b) => b.id === boardLibraryId) ?? null,
    [boards, boardLibraryId],
  );
  const supported = status?.boards.includes(boardLibraryId) ?? false;
  const generic = status?.generic.includes(boardLibraryId) ?? false;
  const image = status?.images[boardLibraryId];

  useEffect(() => {
    let cancelled = false;
    api.circuitpythonFirmwareStatus()
      .then((s) => { if (!cancelled) setStatus(s); })
      .catch((e) => {
        if (!cancelled) {
          setStatus({ available: false, version: null, boards: [], generic: [], images: {}, reason: e instanceof Error ? e.message : String(e) });
        }
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!supported) { setStarter(null); return; }
    let cancelled = false;
    api.circuitpythonCode(boardLibraryId)
      .then((code) => { if (!cancelled) setStarter(code); })
      .catch(() => { if (!cancelled) setStarter(null); });
    return () => { cancelled = true; };
  }, [supported, boardLibraryId]);

  useEffect(() => () => { void sessionRef.current?.close(); }, []);

  function appendLog(line: string) {
    setLog((l) => [...l.slice(-200), line]);
  }

  async function handleFlash() {
    setError(null);
    setPhase("fetching");
    try {
      const { data, offset } = await api.circuitpythonFirmware(boardLibraryId);
      appendLog(`fetched CircuitPython ${status?.version ?? "release"} image (${(data.length / 1024).toFixed(0)} KiB)`);
      setPhase("flashing");
      const session = await flashToTarget(target, {
        images: [{ data, address: offset }],
        eraseAll: true,
        chip: board?.chip_variant,
        onProgress: (written, total) => setProgress(total ? written / total : 0),
        onLog: appendLog,
        onSerial: (text) => setSerial((s) => (s + text).slice(-8000)),
      });
      sessionRef.current = session;
      setPhase("flashed");
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : e instanceof Error ? e.message : String(e));
      setPhase("idle");
    }
  }

  /** Write code.py straight onto the CIRCUITPY drive via the File System
   *  Access API (Chrome/Edge -- same support matrix as WebSerial). */
  async function handleSaveToDrive() {
    if (!starter) return;
    setError(null);
    try {
      const picker = (window as Window & { showDirectoryPicker?: (opts?: unknown) => Promise<FileSystemDirectoryHandle> }).showDirectoryPicker;
      if (!picker) throw new Error("This browser can't write files directly. Use Download and copy code.py over by hand.");
      const dir = await picker.call(window, { mode: "readwrite" });
      const file = await dir.getFileHandle("code.py", { create: true });
      const writable = await (file as FileSystemFileHandle & { createWritable: () => Promise<{ write: (d: string) => Promise<void>; close: () => Promise<void> }> }).createWritable();
      await writable.write(starter);
      await writable.close();
      setSaved(`code.py saved to ${dir.name}/`);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return; // user cancelled the picker
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function handleDownload() {
    if (!starter) return;
    const url = URL.createObjectURL(new Blob([starter], { type: "text/x-python" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "code.py";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-3">
      {status !== null && !status.available && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">
          <div className="font-semibold">Firmware download unavailable</div>
          <div className="mt-1">{status.reason}</div>
        </div>
      )}

      {generic && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">
          No official CircuitPython build for <code className="font-mono">{board?.name ?? boardLibraryId}</code> —
          flashing the pin-compatible <code className="font-mono">{image}</code> image.
          It boots, but pin names and flash/PSRAM sizing may differ; the starter
          code.py prints the pins the build actually exposes.
        </div>
      )}

      <FlashTargetPicker
        target={target}
        onChange={setTarget}
        disabled={phase === "fetching" || phase === "flashing"}
      />

      <div className="flex items-center justify-between gap-3 text-xs text-ink-dim">
        <div>
          {!design
            ? "Open a design with an ESP32-family board (ESP8266 has no CircuitPython port)."
            : supported
              ? <>Flashing CircuitPython {status?.version ?? ""} (<code className="font-mono text-ink">{image}</code>) for <code className="font-mono text-ink">{board?.name ?? boardLibraryId}</code>, full-chip erase.</>
              : <>No CircuitPython build for <code className="font-mono text-ink">{board?.name ?? boardLibraryId}</code>. ESP32/S3/C3/C6 boards are supported; ESP8266 is not.</>}
        </div>
        <Button
          variant="primary"
          disabled={!supported || !status?.available || phase === "fetching" || phase === "flashing"}
          onClick={handleFlash}
        >
          <Zap className="h-3.5 w-3.5" />
          {phase === "fetching" ? "Fetching…" : phase === "flashing" ? `Flashing ${(progress * 100).toFixed(0)}%` : "Flash CircuitPython"}
        </Button>
      </div>

      {log.length > 0 && (
        <pre className="max-h-32 overflow-auto rounded-lg bg-surface-0 p-2 font-mono text-[11px] leading-snug text-ink-dim ring-1 ring-line">
          {log.join("\n")}
        </pre>
      )}

      {phase === "flashed" && (
        <div className="space-y-2 rounded-lg border border-line bg-surface-2/40 p-3 text-xs text-ink-dim">
          <p>
            Device flashed. After it reboots it mounts a <code className="font-mono text-ink">CIRCUITPY</code>{" "}
            USB drive — close this dialog to free the serial port, then drop a{" "}
            <code className="font-mono text-ink">code.py</code> onto the drive to run it.
          </p>
          {starter && (
            <>
              <div className="text-xs font-medium text-ink">Starter code.py for this board</div>
              <pre className="max-h-40 overflow-auto rounded-md bg-surface-0 p-2 font-mono text-[10px] text-ink-dim ring-1 ring-line">
                {starter}
              </pre>
              <div className="flex items-center gap-2">
                <Button variant="primary" onClick={handleSaveToDrive}>
                  <UploadCloud className="h-3.5 w-3.5" />
                  Save to CIRCUITPY
                </Button>
                <Button onClick={handleDownload}>Download code.py</Button>
                {saved && <span className="text-[10px] text-emerald-300/90">{saved}</span>}
              </div>
            </>
          )}
        </div>
      )}

      {serial && (
        <pre className="max-h-40 overflow-auto rounded-lg bg-surface-0 p-2 font-mono text-[11px] leading-snug text-emerald-300/90 ring-1 ring-line">
          {serial}
        </pre>
      )}

      {error && (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-200 whitespace-pre-wrap">
          {error}
        </div>
      )}
    </div>
  );
}

type TasmotaPhase = "idle" | "fetching" | "flashing" | "flashed" | "pushing" | "pushed";

function TasmotaFlash({ design, boards }: { design: Design | null; boards: BoardSummary[] | null }) {
  const [status, setStatus] = useState<{ available: boolean; reason: string | null } | null>(null);
  const [phase, setPhase] = useState<TasmotaPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number>(0);
  const [log, setLog] = useState<string[]>([]);
  const [serial, setSerial] = useState<string>("");
  const [template, setTemplate] = useState<TasmotaTemplate | null>(null);
  const [templateWarnings, setTemplateWarnings] = useState<string[]>([]);
  const [ssid, setSsid] = useState("");
  const [password, setPassword] = useState("");
  const [target, setTarget] = useState<FlashTarget>({ kind: "usb" });
  const sessionRef = useRef<FlashSession | null>(null);

  const boardLibraryId = String((design?.board as Record<string, unknown> | undefined)?.library_id ?? "");
  const board = useMemo(
    () => (boards ?? []).find((b) => b.id === boardLibraryId) ?? null,
    [boards, boardLibraryId],
  );
  const chip = board?.chip_variant ?? null;

  useEffect(() => {
    let cancelled = false;
    api.tasmotaFirmwareStatus()
      .then((s) => { if (!cancelled) setStatus(s); })
      .catch((e) => {
        if (!cancelled) setStatus({ available: false, reason: e instanceof Error ? e.message : String(e) });
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!design) { setTemplate(null); return; }
    let cancelled = false;
    api.tasmotaTemplate(design)
      .then((r) => {
        if (cancelled) return;
        setTemplate(r.template);
        setTemplateWarnings(r.warnings);
      })
      .catch(() => { if (!cancelled) setTemplate(null); });
    return () => { cancelled = true; };
  }, [design]);

  useEffect(() => () => { void sessionRef.current?.close(); }, []);

  function appendLog(line: string) {
    setLog((l) => [...l.slice(-200), line]);
  }

  async function handleFlash() {
    if (!chip) return;
    setError(null);
    setPhase("fetching");
    try {
      const { data, offset } = await api.tasmotaFirmware(chip);
      appendLog(`fetched release image (${(data.length / 1024).toFixed(0)} KiB) for ${chip}`);
      setPhase("flashing");
      const session = await flashToTarget(target, {
        images: [{ data, address: offset }],
        eraseAll: true,
        chip: board?.chip_variant,
        onProgress: (written, total) => setProgress(total ? written / total : 0),
        onLog: appendLog,
        onSerial: (text) => setSerial((s) => (s + text).slice(-8000)),
      });
      sessionRef.current = session;
      setPhase("flashed");
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : e instanceof Error ? e.message : String(e));
      setPhase("idle");
    }
  }

  async function handlePush() {
    const session = sessionRef.current;
    if (!session || !template) return;
    setError(null);
    setPhase("pushing");
    try {
      for (const cmd of tasmotaConfigCommands(template, ssid.trim() || undefined, password || undefined)) {
        await session.write(cmd + "\r\n");
        appendLog(`> ${cmd.replace(password ? password : " ", "***")}`);
        await new Promise((r) => setTimeout(r, 500));
      }
      setPhase("pushed");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("flashed");
    }
  }

  const busy = phase === "fetching" || phase === "flashing" || phase === "pushing";

  return (
    <div className="space-y-3">
      {status !== null && !status.available && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">
          <div className="font-semibold">Firmware download unavailable</div>
          <div className="mt-1">{status.reason}</div>
        </div>
      )}

      <FlashTargetPicker target={target} onChange={setTarget} disabled={busy} />

      <div className="flex items-center justify-between gap-3 text-xs text-ink-dim">
        <div>
          {chip
            ? <>Flashing the official Tasmota release for <code className="font-mono text-ink">{chip}</code> ({board?.name}), full-chip erase.</>
            : "Open a design to derive the chip, or connect any supported board."}
        </div>
        <Button
          variant="primary"
          disabled={!chip || !status?.available || busy}
          onClick={handleFlash}
        >
          <Zap className="h-3.5 w-3.5" />
          {phase === "fetching" ? "Fetching…" : phase === "flashing" ? `Flashing ${(progress * 100).toFixed(0)}%` : "Flash Tasmota"}
        </Button>
      </div>

      {log.length > 0 && (
        <pre className="max-h-32 overflow-auto rounded-lg bg-surface-0 p-2 font-mono text-[11px] leading-snug text-ink-dim ring-1 ring-line">
          {log.join("\n")}
        </pre>
      )}

      {(phase === "flashed" || phase === "pushing" || phase === "pushed") && (
        <div className="space-y-2 rounded-lg border border-line bg-surface-2/40 p-3">
          <div className="text-xs font-medium text-ink">Push configuration over serial</div>
          {sessionRef.current === null && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-2 text-[11px] text-amber-200">
              Flashed on a workbench slot, so there is no serial session here to
              push the template through — the bench owns the port. Push the
              config from a local USB flash, or configure the device over its
              own WiFi portal.
            </div>
          )}
          {template ? (
            <pre className="max-h-24 overflow-auto rounded-md bg-surface-0 p-2 font-mono text-[10px] text-ink-dim ring-1 ring-line">
              {JSON.stringify(template)}
            </pre>
          ) : (
            <div className="text-[11px] text-ink-faint">
              No design open — flashing works, but there is no template to push.
            </div>
          )}
          {templateWarnings.length > 0 && (
            <ul className="text-[10px] text-amber-200">
              {templateWarnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          )}
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <FieldLabel>wifi ssid (optional)</FieldLabel>
              <Input value={ssid} onChange={(e) => setSsid(e.target.value)} placeholder="left blank: skip WiFi" />
            </div>
            <div className="space-y-1">
              <FieldLabel>wifi password</FieldLabel>
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-[10px] text-ink-faint">
              Credentials go straight to the device over serial; they are never
              sent to the server or stored in the design.
            </span>
            <Button
              variant="primary"
              disabled={!template || phase === "pushing" || sessionRef.current === null}
              onClick={handlePush}
            >
              <Radio className="h-3.5 w-3.5" />
              {phase === "pushing" ? "Pushing…" : phase === "pushed" ? "Push again" : "Push config"}
            </Button>
          </div>
        </div>
      )}

      {serial && (
        <pre className="max-h-40 overflow-auto rounded-lg bg-surface-0 p-2 font-mono text-[11px] leading-snug text-emerald-300/90 ring-1 ring-line">
          {serial}
        </pre>
      )}

      {error && (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-200 whitespace-pre-wrap">
          {error}
        </div>
      )}
    </div>
  );
}
