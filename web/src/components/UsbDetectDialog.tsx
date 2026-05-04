import { useEffect, useState } from "react";
import type { BoardSummary, Design } from "../types/api";
import {
  bootstrapDesign,
  candidateBoardsFor,
  type DetectedChip,
} from "../lib/bootstrap";
import { detectChip, isWebSerialSupported } from "../lib/usb-detect";

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

  function handleAdopt() {
    if (phase.kind !== "detected") return;
    const board = boards?.find((b) => b.id === pickedBoardId);
    if (!board) return;
    onAdopt(bootstrapDesign(board, phase.chip));
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="m-4 max-h-[85vh] w-full max-w-2xl overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-zinc-100">Connect device</div>
            <div className="text-xs text-zinc-500">
              Detect an ESP chip via WebSerial and bootstrap a fresh design.
            </div>
          </div>
          <button
            onClick={onCancel}
            className="rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-900"
          >
            Close
          </button>
        </div>

        <div className="space-y-4 p-4 text-sm">
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
              onAdopt={handleAdopt}
              onRetry={handleConnect}
              log={log}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function UnsupportedNotice() {
  return (
    <div className="rounded border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-100">
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
      <ol className="space-y-1.5 list-decimal pl-5 text-xs text-zinc-300">
        <li>Plug your ESP board in via USB.</li>
        <li>Click <b>Connect</b> below; the browser will ask which serial port to use.</li>
        <li>esptool-js will sync with the bootloader and report the chip family.</li>
        <li>Pick a matching board from the studio library and we'll seed a fresh design.</li>
      </ol>
      <button
        onClick={onConnect}
        className="rounded bg-blue-500/20 px-3 py-1.5 text-sm text-blue-100 ring-1 ring-blue-400/40 hover:bg-blue-500/30"
      >
        Connect
      </button>
    </>
  );
}

function ConnectingPanel({ log }: { log: string[] }) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-sm text-blue-200">
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-400" />
        Syncing with the bootloader...
      </div>
      <p className="mb-2 text-xs text-zinc-500">
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
      <div className="rounded border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-200">
        <div className="font-semibold">Detection failed</div>
        <div className="mt-1 whitespace-pre-wrap">{message}</div>
      </div>
      {log.length > 0 && <LogBox log={log} />}
      <button
        onClick={onRetry}
        className="rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-200 hover:bg-zinc-900"
      >
        Retry
      </button>
    </div>
  );
}

function DetectedPanel({
  chip, boards, pickedBoardId, onPick, onAdopt, onRetry, log,
}: {
  chip: DetectedChip;
  boards: BoardSummary[] | null;
  pickedBoardId: string;
  onPick: (id: string) => void;
  onAdopt: () => void;
  onRetry: () => void;
  log: string[];
}) {
  const candidates = boards ? candidateBoardsFor(boards, chip.chipName) : [];
  const noMatch = candidates.length === 0;
  const showAll = noMatch && boards;

  return (
    <div className="space-y-3">
      <div className="rounded border border-emerald-500/40 bg-emerald-500/5 p-3 text-xs">
        <div className="font-semibold text-emerald-200">Detected: {chip.chipName}</div>
        {chip.mac && <div className="mt-0.5 font-mono text-zinc-400">MAC {chip.mac}</div>}
      </div>

      {noMatch && (
        <div className="rounded border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-100">
          No board in the library matches this chip family yet. Pick the closest
          one — you can change the board afterwards from the inspector.
        </div>
      )}

      <div>
        <div className="mb-2 text-xs uppercase tracking-wide text-zinc-500">
          {noMatch ? "All boards" : `Matching boards (${candidates.length})`}
        </div>
        <ul className="space-y-1">
          {(showAll ? boards : candidates).map((b) => (
            <li key={b.id}>
              <label className="flex cursor-pointer items-center gap-2 rounded border border-zinc-800 bg-zinc-900/40 px-2 py-1.5 hover:bg-zinc-900">
                <input
                  type="radio"
                  name="board"
                  value={b.id}
                  checked={pickedBoardId === b.id}
                  onChange={() => onPick(b.id)}
                  className="h-3.5 w-3.5"
                />
                <span className="flex-1 text-xs">
                  <span className="text-zinc-100">{b.name}</span>
                  <span className="ml-2 text-zinc-500">
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
        <details className="text-xs text-zinc-500">
          <summary className="cursor-pointer hover:text-zinc-300">Show detection log</summary>
          <LogBox log={log} className="mt-2" />
        </details>
      )}

      <div className="flex justify-end gap-2 pt-2">
        <button
          onClick={onRetry}
          className="rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-900"
        >
          Re-detect
        </button>
        <button
          disabled={!pickedBoardId}
          onClick={onAdopt}
          className="rounded bg-blue-500/20 px-3 py-1.5 text-sm text-blue-100 ring-1 ring-blue-400/40 enabled:hover:bg-blue-500/30 disabled:opacity-40"
        >
          Bootstrap design →
        </button>
      </div>
    </div>
  );
}

function LogBox({ log, className = "" }: { log: string[]; className?: string }) {
  return (
    <pre
      className={`max-h-40 overflow-auto rounded border border-zinc-800 bg-zinc-900/50 p-2 font-mono text-[11px] text-zinc-400 ${className}`}
    >
      {log.join("\n")}
    </pre>
  );
}
