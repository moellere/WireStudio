import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Design, FleetPushResponse, FleetRunStatus, DashboardPushResponse,
  DashboardStatus,
  FleetJobLogResponse,
  FleetStatus,
  RepoPushResponse } from "../types/api";
import { Button, Code, Dialog, FieldLabel, Input } from "./ui";

const LOG_POLL_INTERVAL_MS = 1500;

const VERDICT_STYLE: Record<string, string> = {
  passed: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40",
  failed: "bg-rose-500/15 text-rose-300 ring-rose-500/40",
  cancelled: "bg-amber-500/15 text-amber-300 ring-amber-500/40",
  running: "bg-accent-500/15 text-accent-300 ring-accent-500/40",
  unknown: "bg-surface-3/40 text-ink-dim ring-line-strong",
};
const VERDICT_LABEL: Record<string, string> = {
  passed: "Compile passed",
  failed: "Compile failed",
  cancelled: "Compile cancelled",
  running: "Compiling…",
  unknown: "Verdict unknown",
};

interface Props {
  design: Design;
  /** When true, ask the server to refuse the push if the design has any
   *  warn/error compatibility entries. Defaults to false; the App's
   *  header strict-mode toggle drives this. */
  strict?: boolean;
  onClose: () => void;
}

/**
 * "Push to fleet" modal. Renders the current design's YAML and POSTs it to
 * the fleet-for-esphome ha-addon configured via FLEET_URL/FLEET_TOKEN on
 * the studio API. The user can optionally enqueue a compile in the same
 * round-trip; when the build finishes the dialog surfaces the pass/fail
 * verdict fetched from the addon's job queue.
 *
 * Status is fetched on open so we can disable the button + show why the
 * fleet isn't reachable when it isn't.
 */
/** Where the YAML goes and who compiles it. The compiling ones answer the
 * same status / push / log / verdict calls, so the dialog only swaps the
 * table; the repository only stores the file. */
type Backend = "fleet" | "dashboard" | "repo";

const noCompile = () => Promise.reject(new Error("this path does not compile"));

const BACKENDS: Record<Backend, {
  label: string;
  title: string;
  place: string;
  subtitle: string;
  envHint: string;
  compiles: boolean;
  status: () => Promise<FleetStatus | DashboardStatus>;
  push: (body: { design: Design; compile: boolean; device_name?: string; strict: boolean; target?: string }, overwrite: boolean) => Promise<FleetPushResponse | DashboardPushResponse | RepoPushResponse>;
  jobLog: (runId: string, offset: number) => Promise<FleetJobLogResponse>;
  runStatus: (runId: string) => Promise<{ verdict: string }>;
  firmware: (runId: string) => Promise<Uint8Array>;
  streamPath: (runId: string) => string;
}> = {
  fleet: {
    label: "fleet-for-esphome",
    title: "Push to fleet",
    place: "the fleet",
    compiles: true,
    subtitle: "Send the rendered YAML to fleet-for-esphome (ha-addon).",
    envHint: "FLEET_URL and FLEET_TOKEN",
    status: () => api.fleetStatus(),
    push: (body) => api.fleetPush(body),
    jobLog: (runId, offset) => api.fleetJobLog(runId, offset),
    runStatus: (runId) => api.fleetRunStatus(runId),
    firmware: (runId) => api.fleetFirmware(runId, { factory: true }),
    streamPath: (runId) => `/api/fleet/jobs/${encodeURIComponent(runId)}/log/stream`,
  },
  dashboard: {
    label: "ESPHome dashboard",
    title: "Push to ESPHome dashboard",
    place: "the dashboard",
    compiles: true,
    subtitle: "Write the rendered YAML to an ESPHome dashboard (HA add-on or standalone) and compile there.",
    envHint: "ESPHOME_DASHBOARD_URL",
    status: () => api.esphomeDashboardStatus(),
    push: (body) => api.esphomeDashboardPush(body),
    jobLog: (runId, offset) => api.esphomeDashboardJobLog(runId, offset),
    runStatus: (runId) => api.esphomeDashboardRunStatus(runId),
    firmware: (runId) => api.esphomeDashboardFirmware(runId, { factory: true }),
    streamPath: (runId) => `/api/esphome/jobs/${encodeURIComponent(runId)}/log/stream`,
  },
  repo: {
    label: "ESPHome repo",
    title: "Push to ESPHome repo",
    place: "the repository",
    subtitle: "Commit the rendered YAML to the GitHub repository of ESPHome configs. Nothing is compiled.",
    envHint: "ESPHOME_REPO and ESPHOME_REPO_TOKEN",
    compiles: false,
    status: () => api.esphomeRepoStatus(),
    push: ({ design, device_name, strict }, overwrite) => api.esphomeRepoPush({ design, device_name, strict, overwrite }),
    jobLog: noCompile,
    runStatus: noCompile,
    firmware: noCompile,
    streamPath: () => "",
  },
};

export function PushToFleetDialog({ design, strict = false, onClose }: Props) {
  const [backend, setBackend] = useState<Backend>("fleet");
  const [dashboardStatus, setDashboardStatus] = useState<DashboardStatus | null>(null);
  const [dashTarget, setDashTarget] = useState<string | null>(null);
  const be = BACKENDS[backend];
  const [backendStatus, setStatus] = useState<FleetStatus | null>(null);
  const targets = dashboardStatus?.targets ?? [];
  const chosenTarget = backend === "dashboard"
    ? targets.find((t) => t.name === dashTarget) ?? targets.find((t) => t.default)
    : undefined;
  const status: FleetStatus | DashboardStatus | null = chosenTarget ?? backendStatus;
  const [statusError, setStatusError] = useState<string | null>(null);
  const fleet = (design.fleet as Record<string, unknown> | undefined) ?? undefined;
  const fleetDeviceName = typeof fleet?.device_name === "string" ? fleet.device_name : "";
  const designId = typeof design.id === "string" ? design.id : "";
  const [deviceName, setDeviceName] = useState<string>(fleetDeviceName || designId);
  const [compile, setCompile] = useState<boolean>(false);
  const [pushing, setPushing] = useState(false);
  const [overwrite, setOverwrite] = useState<boolean>(false);
  const [result, setResult] = useState<(FleetPushResponse & Partial<RepoPushResponse>) | null>(null);
  const [pushError, setPushError] = useState<string | null>(null);

  const [logText, setLogText] = useState<string>("");
  const [logFinished, setLogFinished] = useState<boolean>(false);
  const [logError, setLogError] = useState<string | null>(null);
  const [logTransport, setLogTransport] = useState<"sse" | "poll" | null>(null);
  const [verdict, setVerdict] = useState<FleetRunStatus | null>(null);
  const logScrollRef = useRef<HTMLPreElement | null>(null);
  const pollAbortRef = useRef<{ stop: boolean }>({ stop: false });
  const eventSourceRef = useRef<EventSource | null>(null);

  type FlashState =
    | { kind: "idle" }
    | { kind: "fetching" }
    | { kind: "flashing"; written: number; total: number }
    | { kind: "flashed"; bytes: number }
    | { kind: "error"; message: string };
  const [flashState, setFlashState] = useState<FlashState>({ kind: "idle" });
  const [serialLog, setSerialLog] = useState<string>("");
  const flashSessionRef = useRef<{ close: () => Promise<void> } | null>(null);
  useEffect(() => () => {
    void flashSessionRef.current?.close();
  }, []);

  /** Write the image this run built to a board on local USB: the merged
   *  image at 0x0 after a full erase, as for a first flash. */
  async function handleFlash(runId: string) {
    setFlashState({ kind: "fetching" });
    setSerialLog("");
    try {
      await flashSessionRef.current?.close();
      flashSessionRef.current = null;
      const data = await be.firmware(runId);
      const { flashFirmware } = await import("../lib/flash");
      setFlashState({ kind: "flashing", written: 0, total: data.byteLength });
      flashSessionRef.current = await flashFirmware({
        images: [{ data, address: 0x0 }],
        eraseAll: true,
        onProgress: (written, total) => setFlashState({ kind: "flashing", written, total }),
        onSerial: (text) => setSerialLog((prev) => (prev + text).slice(-8000)),
      });
      setFlashState({ kind: "flashed", bytes: data.byteLength });
    } catch (e) {
      const detail = e instanceof ApiError ? (e.body as { detail?: unknown } | undefined)?.detail : undefined;
      setFlashState({
        kind: "error",
        message: e instanceof ApiError
          ? `${e.status}: ${typeof detail === "string" ? detail : e.message}`
          : e instanceof Error ? e.message : String(e),
      });
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [fleetS, dashS, repoS] = await Promise.all([
          api.fleetStatus(),
          api.esphomeDashboardStatus().catch(() => ({ available: false, reason: "unreachable" } as DashboardStatus)),
          api.esphomeRepoStatus().catch(() => ({ available: false, reason: "unreachable" } as FleetStatus)),
        ]);
        if (cancelled) return;
        setDashboardStatus(dashS);
        // Default to whichever path is actually configured.
        if (!fleetS.available && dashS.available) {
          setBackend("dashboard");
          setStatus(dashS);
        } else if (!fleetS.available && repoS.available) {
          setBackend("repo");
          setStatus(repoS);
        } else {
          setStatus(fleetS);
        }
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof ApiError ? `${e.status}: ${e.message}` :
          e instanceof Error ? e.message : String(e);
        setStatusError(msg);
      }
    })();
    return () => {
      cancelled = true;
      pollAbortRef.current.stop = true;
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
    };
  }, []);

  // Auto-scroll the log viewer when new content lands.
  async function switchBackend(next: Backend) {
    setBackend(next);
    setResult(null);
    setVerdict(null);
    setLogText("");
    setPushError(null);
    try {
      const s = await BACKENDS[next].status();
      setStatus(s);
      if (next === "dashboard") setDashboardStatus(s);
    } catch (e) {
      setStatusError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (logScrollRef.current) {
      logScrollRef.current.scrollTop = logScrollRef.current.scrollHeight;
    }
  }, [logText]);

  // When the build log reaches a terminal state, fetch the compile
  // verdict for the run. Best-effort: the log already shows what
  // happened, so a verdict-fetch failure stays silent.
  useEffect(() => {
    const runId = result?.run_id;
    if (!logFinished || !runId) return;
    let cancelled = false;
    (async () => {
      try {
        const v = await be.runStatus(runId);
        if (!cancelled) setVerdict(v as FleetRunStatus);
      } catch {
        // verdict unavailable -- leave it unset
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [logFinished, result?.run_id]);

  /**
   * Open an EventSource against `/api/fleet/jobs/<runId>/log/stream` and
   * append each chunk to the log viewer. Returns true on success (the
   * EventSource opened); returns false if the browser doesn't have
   * EventSource at all so the caller can fall back to polling.
   *
   * The server emits `data:` frames (chunks), an `event: done` frame at
   * the end of a successful run, and an `event: error` frame when the
   * addon rejects the stream (e.g., unknown run_id). A transport-level
   * onerror flips us back to polling so a flaky proxy never strands the
   * UI in "tailing…" forever.
   */
  function streamJobLog(runId: string): boolean {
    if (typeof EventSource === "undefined") return false;
    setLogText("");
    setLogFinished(false);
    setLogError(null);
    setLogTransport("sse");
    const es = new EventSource(be.streamPath(runId));
    eventSourceRef.current = es;
    let lastOffset = 0;

    es.onmessage = (ev) => {
      try {
        const chunk = JSON.parse(ev.data) as {
          log: string; offset: number; finished: boolean;
        };
        if (chunk.log) setLogText((prev) => prev + chunk.log);
        lastOffset = chunk.offset;
        if (chunk.finished) {
          setLogFinished(true);
          es.close();
          eventSourceRef.current = null;
        }
      } catch {
        // Ignore malformed frames; the next valid one will land.
      }
    };
    es.addEventListener("done", () => {
      setLogFinished(true);
      es.close();
      eventSourceRef.current = null;
    });
    es.addEventListener("error", (ev) => {
      // Server-emitted error frame (named `error`). The data carries a
      // {message} envelope; surface it and stop -- no fallback poll
      // because this is a logical failure, not a transport hiccup.
      const me = ev as MessageEvent;
      try {
        const data = JSON.parse(me.data ?? "{}") as { message?: string };
        if (data.message) setLogError(data.message);
      } catch {
        // Server-emitted error without a parseable body.
      }
      es.close();
      eventSourceRef.current = null;
    });
    es.onerror = () => {
      // Transport-level failure (network, proxy buffering, server died).
      // Fall back to polling from the offset we last accepted.
      if (es.readyState === EventSource.CLOSED) return;
      es.close();
      eventSourceRef.current = null;
      setLogTransport("poll");
      void pollJobLog(runId, lastOffset);
    };
    return true;
  }

  /** HTTP polling fallback. Used directly when EventSource isn't
   *  available, or as a fallback when the SSE transport errors. */
  async function pollJobLog(runId: string, startOffset = 0) {
    const abort = pollAbortRef.current;
    abort.stop = false;
    let offset = startOffset;
    if (startOffset === 0) {
      setLogText("");
      setLogFinished(false);
      setLogError(null);
    }
    setLogTransport("poll");
    while (!abort.stop) {
      try {
        const chunk = await be.jobLog(runId, offset);
        if (abort.stop) return;
        if (chunk.log) setLogText((prev) => prev + chunk.log);
        offset = chunk.offset;
        if (chunk.finished) {
          setLogFinished(true);
          return;
        }
      } catch (e) {
        const msg = e instanceof ApiError ? `${e.status}: ${e.message}` :
          e instanceof Error ? e.message : String(e);
        setLogError(msg);
        return;
      }
      await new Promise((res) => setTimeout(res, LOG_POLL_INTERVAL_MS));
    }
  }

  /** Pick the best transport for tailing this run's log. Tries SSE
   *  first; the polling path is the fallback the SSE handler installs
   *  on transport error. */
  function tailJobLog(runId: string) {
    if (!streamJobLog(runId)) {
      void pollJobLog(runId);
    }
  }

  async function handlePush() {
    setPushing(true);
    setPushError(null);
    setResult(null);
    setVerdict(null);
    setFlashState({ kind: "idle" });
    try {
      const pushed = be.push({
        design,
        compile: compile && be.compiles,
        device_name: deviceName.trim() || undefined,
        strict,
        target: chosenTarget?.name,
      }, overwrite);
      const r = await pushed as FleetPushResponse & Partial<RepoPushResponse>;
      setResult(r);
      if (r.run_id) {
        // Fire-and-forget: SSE first, polling as a fallback. Both paths
        // respect the abort/event-source refs cleaned up on unmount.
        tailJobLog(r.run_id);
      }
    } catch (e) {
      let msg: string;
      if (e instanceof ApiError) {
        const body = e.body as
          | { detail?: unknown }
          | undefined;
        const detail = body?.detail;
        if (
          typeof detail === "object" && detail !== null &&
          (detail as { error?: string }).error === "strict_mode_blocked"
        ) {
          // Surface the strict envelope's friendly message; the warnings
          // themselves already render in the design pane via the regular
          // compatibility flow.
          const d = detail as { message?: string; warnings?: unknown[] };
          msg = `${e.status}: ${d.message ?? "strict mode refused the push"}`;
        } else if (
          typeof detail === "object" && detail !== null &&
          (detail as { error?: string }).error === "file_exists"
        ) {
          msg = `${(detail as { message?: string }).message ?? "the file already exists"}. Tick "Replace an existing file" to commit over it.`;
        } else {
          msg = `${e.status}: ${typeof detail === "string" ? detail : e.message}`;
        }
      } else {
        msg = e instanceof Error ? e.message : String(e);
      }
      setPushError(msg);
    } finally {
      setPushing(false);
    }
  }

  const canPush = !pushing && status?.available && deviceName.trim().length > 0;

  return (
    <Dialog
      title={be.title}
      subtitle={be.subtitle}
      onClose={onClose}
      maxWidth="max-w-xl"
      footer={
        <>
          <Button onClick={onClose}>{result ? "Done" : "Cancel"}</Button>
          <Button variant="primary" disabled={!canPush} onClick={handlePush}>
            {pushing ? "Pushing…" : compile && be.compiles ? "Push & compile →" : "Push →"}
          </Button>
        </>
      }
    >
      <div className="space-y-4 text-sm">
        <div className="flex gap-1 rounded-md bg-surface-2/60 p-1 text-xs" role="radiogroup" aria-label="Build path">
          {(Object.keys(BACKENDS) as Backend[]).map((key) => (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={backend === key}
              onClick={() => backend !== key && void switchBackend(key)}
              className={`flex-1 rounded px-2 py-1 ${backend === key ? "bg-surface-1 text-ink shadow-pop" : "text-ink-dim hover:text-ink"}`}
            >
              {BACKENDS[key].label}
              {key === "dashboard" && dashboardStatus?.available && backend !== key && (
                <span className="ml-1 text-emerald-400">•</span>
              )}
            </button>
          ))}
        </div>

        {backend === "dashboard" && targets.length > 1 && (
          <div className="space-y-1">
            <FieldLabel>dashboard</FieldLabel>
            <select
              aria-label="Dashboard"
              value={chosenTarget?.name ?? ""}
              onChange={(e) => {
                setDashTarget(e.target.value);
                setResult(null);
                setVerdict(null);
                setLogText("");
                setPushError(null);
              }}
              className="w-full rounded-md border border-line bg-surface-2/60 px-2 py-1 text-xs text-ink"
            >
              {targets.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.label}{t.default ? " (default)" : ""}{t.available ? "" : " — unavailable"}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Status section */}
        <div className="rounded-md border border-line bg-surface-2/40 p-3">
          <div className="text-[11px] uppercase tracking-wider text-ink-faint">{be.label} status</div>
          {statusError ? (
            <div className="mt-1 text-xs text-rose-400">error: {statusError}</div>
          ) : status === null ? (
            <div className="mt-1 text-xs text-ink-faint">checking…</div>
          ) : status.available ? (
            <div className="mt-1 text-xs text-emerald-400">
              connected · {status.url || be.label}
            </div>
          ) : (
            <div className="mt-1 space-y-1 text-xs">
              <div className="text-amber-300">unavailable: {status.reason || "unknown"}</div>
              <div className="text-ink-faint">
                Set <Code>{be.envHint}</Code> in the API server's
                environment, then restart it.
              </div>
            </div>
          )}
        </div>

        <div className="space-y-1">
          <FieldLabel>device name</FieldLabel>
          <Input
            type="text"
            value={deviceName}
            onChange={(e) =>
              setDeviceName(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))
            }
            placeholder="garage-motion"
            className="font-mono text-xs"
          />
          <p className="text-[11px] text-ink-faint">
            Will be saved {backend === "repo" ? "in" : "on"} {be.place} as <code>{deviceName.trim() || "<name>"}.yaml</code>.
            Lowercase letters, digits, and hyphens only (max 64).
          </p>
        </div>

        {strict && (
          <div className="rounded-md bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200 ring-1 ring-amber-500/30">
            Strict mode is on. The push will be refused if the design has any
            warn/error compatibility entries; resolve them or toggle strict
            off in the header to ship anyway.
          </div>
        )}

        {be.compiles ? (
          <label className="flex cursor-pointer items-start gap-2 rounded-md border border-line bg-surface-2/40 px-3 py-2">
            <input
              type="checkbox"
              checked={compile}
              onChange={(e) => setCompile(e.target.checked)}
              className="mt-0.5 h-3.5 w-3.5"
            />
            <span className="text-xs">
              <span className="text-ink">Compile after upload</span>
              <span className="ml-2 text-ink-faint">
                Enqueues an OTA build for this device on the fleet.
              </span>
            </span>
          </label>
        ) : (
          <label className="flex cursor-pointer items-start gap-2 rounded-md border border-line bg-surface-2/40 px-3 py-2">
            <input
              type="checkbox"
              checked={overwrite}
              onChange={(e) => setOverwrite(e.target.checked)}
              className="mt-0.5 h-3.5 w-3.5"
            />
            <span className="text-xs">
              <span className="text-ink">Replace an existing file</span>
              <span className="ml-2 text-ink-faint">
                Needed only when the file was last changed outside WireStudio.
              </span>
            </span>
          </label>
        )}

        {pushError && (
          <div className="rounded-md bg-rose-500/10 px-3 py-2 text-xs text-rose-200 ring-1 ring-rose-500/30">
            {pushError}
          </div>
        )}

        {result && (
          <div className="rounded-md bg-emerald-500/10 px-3 py-2 text-xs text-emerald-100 ring-1 ring-emerald-500/30">
            {backend === "repo" ? (
              <div>
                {result.changed === false ? "Already up to date: " : result.created ? "Committed new file " : "Committed an update to "}
                {result.url ? (
                  <a href={result.url} target="_blank" rel="noreferrer" className="underline">
                    <code className="rounded-md bg-emerald-500/15 px-1">{result.filename}</code>
                  </a>
                ) : (
                  <code className="rounded-md bg-emerald-500/15 px-1">{result.filename}</code>
                )}
                {result.commit ? ` (${result.commit.slice(0, 7)})` : ""}.
              </div>
            ) : (
              <div>
                {result.created ? "Created" : "Updated"}{" "}
                <code className="rounded-md bg-emerald-500/15 px-1">{result.filename}</code> on{" "}
                {chosenTarget && targets.length > 1 ? chosenTarget.label : be.place}.
              </div>
            )}
            {result.run_id && (
              <div className="mt-1 text-emerald-200/80">
                Compile enqueued: <code>{result.run_id}</code>
                {result.enqueued ? ` (${result.enqueued} job)` : ""}.
              </div>
            )}
          </div>
        )}

        {result?.run_id && (
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <label className="block text-[11px] uppercase tracking-wider text-ink-faint">
                build log
              </label>
              {verdict ? (
                <span
                  className={`rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 ${
                    VERDICT_STYLE[verdict.verdict] ?? VERDICT_STYLE.unknown
                  }`}
                >
                  {VERDICT_LABEL[verdict.verdict] ?? verdict.verdict}
                </span>
              ) : (
                <span className="text-[11px] text-ink-faint">
                  {logFinished
                    ? "finished"
                    : logError
                      ? "stopped"
                      : `tailing… ${logTransport === "sse" ? "(stream)" : logTransport === "poll" ? "(poll)" : ""}`}
                </span>
              )}
            </div>
            <pre
              ref={logScrollRef}
              className="max-h-64 overflow-auto rounded-lg bg-surface-0 p-2 font-mono text-[12px] leading-relaxed text-ink-dim ring-1 ring-line"
            >
              {logText || (logError ? "" : "waiting for first chunk…")}
            </pre>
            {logError && (
              <div className="text-[11px] text-rose-400">log error: {logError}</div>
            )}
            {verdict?.verdict === "passed" && (
              <div className="space-y-1 pt-1">
                <div className="flex items-center gap-2">
                  <Button
                    disabled={flashState.kind === "fetching" || flashState.kind === "flashing"}
                    onClick={() => void handleFlash(result.run_id!)}
                    title="Erases the board, then writes the image this compile built"
                  >
                    {flashState.kind === "fetching"
                      ? "Fetching image…"
                      : flashState.kind === "flashing"
                        ? `Flashing ${Math.round((flashState.written / Math.max(flashState.total, 1)) * 100)}%`
                        : flashState.kind === "flashed" ? "Flash another" : "Flash over USB"}
                  </Button>
                  <span className="text-[11px] text-ink-faint">
                    Full erase, then the built image at 0x0. Needs a WebSerial browser.
                  </span>
                </div>
                {flashState.kind === "flashed" && (
                  <div className="text-[11px] text-emerald-300">
                    Wrote {flashState.bytes.toLocaleString()} bytes; the board has reset into it.
                  </div>
                )}
                {flashState.kind === "error" && (
                  <div className="text-[11px] text-rose-400">flash failed: {flashState.message}</div>
                )}
                {serialLog && (
                  <pre className="max-h-40 overflow-auto rounded-lg bg-surface-0 p-2 font-mono text-[12px] leading-relaxed text-ink-dim ring-1 ring-line">
                    {serialLog}
                  </pre>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </Dialog>
  );
}
