import { useEffect, useState } from "react";
import type { BoardSummary, Design } from "../types/api";
import {
  bootstrapDesign,
  candidateBoardsFor,
  type DetectedChip,
} from "../lib/bootstrap";
import { detectChip, isWebSerialSupported } from "../lib/usb-detect";
import { api } from "../api/client";
import { Button, Dialog } from "./ui";

type Phase =
  | { kind: "idle" }
  | { kind: "connecting" }
  | { kind: "detected"; chip: DetectedChip }
  | { kind: "error"; message: string };

interface Props {
  boards: BoardSummary[] | null;
  onCancel: () => void;
  onAdopt: (design: Design) => void;
}

export function UsbDetectDialog({ boards, onCancel, onAdopt }: Props) {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [log, setLog] = useState<string[]>([]);
  const [pickedBoardId, setPickedBoardId] = useState<string>("");
  const supported = isWebSerialSupported();

  // Reset picked board whenever a new chip is detected.
  useEffect(() => {
    if (phase.kind === "detected" && boards) {
      const candidates = candidateBoardsFor(boards, phase.chip.chipName);
      setPickedBoardId(candidates[0]?.id ?? "");
    }
  }, [phase, boards]);

  async function handleConnect() {
    setLog([]);
    setPhase({ kind: "connecting" });
    try {
      const chip = await detectChip({
        onLog: (line) => setLog((prev) => [...prev, line].slice(-50)),
      });
      setPhase({ kind: "detected", chip });
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setPhase({ kind: "error", message });
    }
  }

  async function handleAdopt() {
    if (phase.kind !== "detected") return;
    const board = boards?.find((b) => b.id === pickedBoardId);
    if (!board) return;
    const base = bootstrapDesign(board, phase.chip);
    // Pre-populate the board's onboard peripherals (LCD, button, IMU, ...).
    // Best-effort: a seeding failure must never block adopting the board.
    try {
      onAdopt(await api.seedOnboard(base));
    } catch {
      onAdopt(base);
    }
  }

  return (
    <Dialog
      title="Connect device"
      subtitle="Detect an ESP chip via WebSerial and bootstrap a fresh design."
      onClose={onCancel}
      maxWidth="max-w-2xl"
      footer={
        phase.kind === "detected" ? (
          <>
            <Button onClick={handleConnect}>Re-detect</Button>
            <Button variant="primary" disabled={!pickedBoardId} onClick={handleAdopt}>
              Bootstrap design →
            </Button>
          </>
        ) : undefined
      }
    >
      <div className="space-y-4 text-sm">
        {supported === "no" && (
          <UnsupportedNotice />
        )}

        {supported === "yes" && phase.kind === "idle" && (
          <IdlePanel onConnect={handleConnect} />
        )}

        {phase.kind === "connecting" && <ConnectingPanel log={log} />}

        {phase.kind === "error" && (
          <ErrorPanel message={phase.message} log={log} onRetry={handleConnect} />
        )}

        {phase.kind === "detected" && (
          <DetectedPanel
            chip={phase.chip}
            boards={boards}
            pickedBoardId={pickedBoardId}
            onPick={setPickedBoardId}
            log={log}
          />
        )}
      </div>
    </Dialog>
  );
}

function UnsupportedNotice() {
  return (
    <div className="rounded-md bg-amber-500/10 p-3 text-xs text-amber-100 ring-1 ring-amber-500/30">
      <div className="mb-1 font-semibold">WebSerial isn't available in this browser.</div>
      <div>
        USB device detection uses the WebSerial API, which currently ships in
        Chromium-based browsers (Chrome, Edge, Brave, Arc). Firefox and Safari
        don't support it. Switch browsers or pick a board manually from the
        examples sidebar.
      </div>
    </div>
  );
}

function IdlePanel({ onConnect }: { onConnect: () => void }) {
  return (
    <>
      <ol className="space-y-1.5 list-decimal pl-5 text-xs text-ink-dim">
        <li>Plug your ESP board in via USB.</li>
        <li>Click <b>Connect</b> below; the browser will ask which serial port to use.</li>
        <li>esptool-js will sync with the bootloader and report the chip family.</li>
        <li>Pick a matching board from the studio library and we'll seed a fresh design.</li>
      </ol>
      <Button variant="primary" onClick={onConnect}>
        Connect
      </Button>
    </>
  );
}

function ConnectingPanel({ log }: { log: string[] }) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-sm text-accent-300">
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent-400" />
        Syncing with the bootloader...
      </div>
      <p className="mb-2 text-xs text-ink-faint">
        If this hangs, hold the BOOT button while clicking Connect, or unplug and retry.
      </p>
      <LogBox log={log} />
    </div>
  );
}

function ErrorPanel({
  message, log, onRetry,
}: {
  message: string;
  log: string[];
  onRetry: () => void;
}) {
  return (
    <div className="space-y-3">
      <div className="rounded-md bg-rose-500/10 p-3 text-xs text-rose-200 ring-1 ring-rose-500/30">
        <div className="font-semibold">Detection failed</div>
        <div className="mt-1 whitespace-pre-wrap">{message}</div>
      </div>
      {log.length > 0 && <LogBox log={log} />}
      <Button onClick={onRetry}>Retry</Button>
    </div>
  );
}

function DetectedPanel({
  chip, boards, pickedBoardId, onPick, log,
}: {
  chip: DetectedChip;
  boards: BoardSummary[] | null;
  pickedBoardId: string;
  onPick: (id: string) => void;
  log: string[];
}) {
  const candidates = boards ? candidateBoardsFor(boards, chip.chipName) : [];
  const noMatch = candidates.length === 0;
  const showAll = noMatch && boards;

  return (
    <div className="space-y-3">
      <div className="rounded-md bg-emerald-500/10 p-3 text-xs ring-1 ring-emerald-500/30">
        <div className="font-semibold text-emerald-200">Detected: {chip.chipName}</div>
        {chip.mac && <div className="mt-0.5 font-mono text-ink-dim">MAC {chip.mac}</div>}
      </div>

      {noMatch && (
        <div className="rounded-md bg-amber-500/10 p-3 text-xs text-amber-100 ring-1 ring-amber-500/30">
          No board in the library matches this chip family yet. Pick the closest
          one — you can change the board afterwards from the inspector.
        </div>
      )}

      <div>
        <div className="mb-2 text-xs uppercase tracking-wider text-ink-faint">
          {noMatch ? "All boards" : `Matching boards (${candidates.length})`}
        </div>
        <ul className="max-h-[45vh] space-y-1 overflow-y-auto pr-1">
          {(showAll ? boards : candidates).map((b) => (
            <li key={b.id}>
              <label
                className={`flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 transition-colors ${
                  pickedBoardId === b.id
                    ? "border-accent-500/50 bg-accent-500/5"
                    : "border-line bg-surface-2/40 hover:border-line-strong hover:bg-surface-2"
                }`}
              >
                <input
                  type="radio"
                  name="board"
                  value={b.id}
                  checked={pickedBoardId === b.id}
                  onChange={() => onPick(b.id)}
                  className="h-3.5 w-3.5"
                />
                <span className="flex-1 text-xs">
                  <span className="text-ink">{b.name}</span>
                  <span className="ml-2 text-ink-faint">
                    {b.chip_variant} · {b.framework}
                    {b.flash_size_mb ? ` · ${b.flash_size_mb}MB` : ""}
                  </span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      </div>

      {log.length > 0 && (
        <details className="text-xs text-ink-faint">
          <summary className="cursor-pointer hover:text-ink-dim">Show detection log</summary>
          <LogBox log={log} className="mt-2" />
        </details>
      )}
    </div>
  );
}

function LogBox({ log, className = "" }: { log: string[]; className?: string }) {
  return (
    <pre
      className={`max-h-40 overflow-auto rounded-md border border-line bg-surface-0/50 p-2 font-mono text-[11px] text-ink-dim ${className}`}
    >
      {log.join("\n")}
    </pre>
  );
}
