/**
 * Enclosure dialog (0.8). Three tabs:
 *
 *   Generate — downloads a parametric `.scad` enclosure (YAPP_Box base
 *              and lid) built from the board's enclosure metadata. Same path as the prior
 *              header-button download; just framed in a dialog so it
 *              shares the modal furniture with the search tab.
 *   Print    — hands the same enclosure to print-warden, which renders,
 *              slices and queues it. The job is offered to the
 *              operator's phone; the studio never starts a print.
 *   Search   — relays to /enclosure/search and renders ranked
 *              community-uploaded models. The Search tab is gated on
 *              at least one source being available; when none are
 *              configured, surfaces the per-source configure_hint.
 *
 * The status fetches happen lazily on first open of their tab so the
 * dialog opens fast.
 */
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type {
  Design,
  EnclosureHit,
  EnclosurePrintJob,
  EnclosurePrintResponse,
  EnclosurePrintStatus,
  EnclosureSearchResponse,
  EnclosureSourceStatus,
  PrintWardenPrinter,
} from "../types/api";
import { Button, Dialog, FieldLabel, Input } from "./ui";

type Tab = "generate" | "print" | "search";

interface Props {
  design: Design;
  /** library_id of the design's board, pulled out at call site so the
   *  dialog doesn't have to walk the design dict itself. */
  boardLibraryId: string;
  /** Display name for the search query construction copy. */
  boardName: string;
  onClose: () => void;
}

const TAB_LABEL: Record<Tab, string> = {
  generate: "Generate (OpenSCAD)",
  print: "Print (print-warden)",
  search: "Search community models",
};

export function EnclosureDialog({ design, boardLibraryId, boardName, onClose }: Props) {
  const [tab, setTab] = useState<Tab>("generate");
  return (
    <Dialog
      title="Enclosure"
      subtitle={`${boardName} (${boardLibraryId})`}
      onClose={onClose}
      maxWidth="max-w-2xl"
    >
      <div className="-mx-5 -mt-4 mb-4 flex border-b border-line text-xs">
        {(["generate", "print", "search"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-2 transition-colors ${
              tab === t
                ? "border-b-2 border-accent-400 text-ink"
                : "text-ink-dim hover:text-ink"
            }`}
          >
            {TAB_LABEL[t]}
          </button>
        ))}
      </div>

      <div className="text-sm">
        {tab === "generate" ? (
          <GenerateTab design={design} />
        ) : tab === "print" ? (
          <PrintTab design={design} />
        ) : (
          <SearchTab boardLibraryId={boardLibraryId} boardName={boardName} />
        )}
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Generate tab
// ---------------------------------------------------------------------------

function GenerateTab({ design }: { design: Design }) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloaded, setDownloaded] = useState(false);

  async function handleGenerate() {
    setDownloading(true);
    setError(null);
    setDownloaded(false);
    try {
      const scad = await api.enclosureScad(design);
      const blob = new Blob([scad], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${design.id ?? "design"}.scad`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setDownloaded(true);
    } catch (e) {
      let msg: string;
      if (e instanceof ApiError) {
        const body = e.body as { detail?: unknown } | undefined;
        const detail = body?.detail;
        msg = `${e.status}: ${typeof detail === "string" ? detail : e.message}`;
      } else {
        msg = e instanceof Error ? e.message : String(e);
      }
      setError(msg);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="space-y-3 text-ink-dim">
      <p className="text-xs leading-relaxed text-ink-dim">
        Downloads a self-contained <code className="text-ink">.scad</code> file
        with a tunables block at the top (wall thickness, clearance, standoff
        geometry). Open in OpenSCAD; press <kbd>F5</kbd> to preview, then export STL
        for printing. Built on YAPP_Box: base and lid side by side, with a ridge and
        snap joins where they meet.
      </p>
      <Button variant="primary" onClick={handleGenerate} disabled={downloading}>
        {downloading ? "Generating…" : downloaded ? "Downloaded ✓ — generate again" : "Generate enclosure →"}
      </Button>
      {error && (
        <div className="rounded-md bg-rose-500/10 px-2 py-1.5 text-xs text-rose-200 ring-1 ring-rose-500/30">
          {error}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Print tab
// ---------------------------------------------------------------------------

/** The enclosure's tunables a user is likely to touch. Defaults mirror the
 *  generated .scad header; only values that differ are sent, so an
 *  untouched form prints the file as generated. */
const TUNABLE_FIELDS: { key: string; label: string; default: number; step: number }[] = [
  { key: "wall", label: "wall (mm)", default: 2.0, step: 0.2 },
  { key: "clearance", label: "PCB clearance (mm)", default: 0.6, step: 0.1 },
  { key: "standoff_h", label: "standoff height (mm)", default: 4.0, step: 0.5 },
  { key: "standoff_hole", label: "standoff hole (mm)", default: 2.5, step: 0.1 },
];

const JOB_POLL_INTERVAL_MS = 10_000;
const SETTLED_STATES = new Set(["completed", "failed", "cancelled", "skipped"]);

const SELECT_CLASS =
  "w-full rounded-md border border-line bg-surface-1 px-1.5 py-1 text-xs text-ink focus:border-accent-500/60 focus:outline-none disabled:opacity-50";

/** The printers `where` resolves to: one by name, or all at a location. */
function printersAt(status: EnclosurePrintStatus | null, where: string): PrintWardenPrinter[] {
  return (status?.printers ?? []).filter((p) => p.name === where || p.location === where);
}

function choices(printers: PrintWardenPrinter[]) {
  return {
    materials: Array.from(new Set(printers.flatMap((p) => p.materials))).sort(),
    qualities: Array.from(new Set(printers.flatMap((p) => p.qualities))).sort(),
    loaded: Array.from(new Set(printers.map((p) => p.loaded_material).filter((m): m is string => !!m))),
  };
}

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const body = e.body as { detail?: unknown } | undefined;
    const detail = body?.detail;
    return `${e.status}: ${typeof detail === "string" ? detail : e.message}`;
  }
  return e instanceof Error ? e.message : String(e);
}

function PrintTab({ design }: { design: Design }) {
  const [status, setStatus] = useState<EnclosurePrintStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [where, setWhere] = useState("");
  const [material, setMaterial] = useState("");
  const [quality, setQuality] = useState("standard");
  const [copies, setCopies] = useState(1);
  const [tunables, setTunables] = useState<Record<string, string>>(
    () => Object.fromEntries(TUNABLE_FIELDS.map((f) => [f.key, String(f.default)])),
  );
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [result, setResult] = useState<EnclosurePrintResponse | null>(null);
  const [job, setJob] = useState<EnclosurePrintJob | null>(null);

  // Picking a place also picks the material loaded there (the warden will
  // not start otherwise) and keeps the quality if its printers offer it.
  function selectWhere(next: string, s: EnclosurePrintStatus | null = status) {
    const c = printersAt(s, next);
    setWhere(next);
    if (!c.length) return;
    const { materials, qualities, loaded } = choices(c);
    setMaterial(loaded[0] ?? materials[0] ?? "");
    setQuality((q) => (qualities.includes(q) ? q : qualities.includes("standard") ? "standard" : qualities[0] ?? ""));
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await api.enclosurePrintStatus();
        if (cancelled) return;
        setStatus(s);
        selectWhere(s.locations[0] ?? s.printers[0]?.name ?? "", s);
      } catch (e) {
        if (!cancelled) setStatusError(errorMessage(e));
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const candidates = printersAt(status, where);
  const { materials, qualities, loaded } = choices(candidates);

  // Poll the staged job until it settles, while the tab is open.
  useEffect(() => {
    if (!result) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const j = await api.enclosurePrintJob(result.job_id);
        if (cancelled) return;
        setJob(j);
        if (!SETTLED_STATES.has(j.state)) timer = window.setTimeout(tick, JOB_POLL_INTERVAL_MS);
      } catch {
        if (!cancelled) timer = window.setTimeout(tick, JOB_POLL_INTERVAL_MS);
      }
    };
    let timer = window.setTimeout(tick, JOB_POLL_INTERVAL_MS);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [result]);

  async function handleSend() {
    setSending(true);
    setSendError(null);
    setResult(null);
    setJob(null);
    const changed: Record<string, number> = {};
    for (const f of TUNABLE_FIELDS) {
      const v = Number(tunables[f.key]);
      if (Number.isFinite(v) && v !== f.default) changed[f.key] = v;
    }
    try {
      const r = await api.enclosurePrint({
        design, where, material, quality, copies,
        tunables: Object.keys(changed).length ? changed : undefined,
      });
      setResult(r);
    } catch (e) {
      setSendError(errorMessage(e));
    } finally {
      setSending(false);
    }
  }

  if (statusError) {
    return (
      <div className="rounded-md bg-rose-500/10 px-2 py-1.5 text-xs text-rose-200 ring-1 ring-rose-500/30">
        {statusError}
      </div>
    );
  }
  if (!status) return <div className="text-xs text-ink-faint">Checking print-warden…</div>;
  if (!status.available) {
    return (
      <div className="space-y-2">
        <div className="rounded-md bg-amber-500/10 px-2 py-1.5 text-xs text-amber-200 ring-1 ring-amber-500/30">
          print-warden unavailable: {status.reason ?? "unknown"}
        </div>
        <p className="text-[11px] text-ink-faint">
          Set <code className="text-ink-dim">PRINT_WARDEN_URL</code> (and
          <code className="text-ink-dim"> PRINT_WARDEN_TOKEN</code> if the warden has one) on the studio API
          and restart it. The Generate tab still downloads the .scad for a manual print.
        </p>
      </div>
    );
  }

  const options = [
    ...status.locations.map((l) => ({ value: l, label: `${l} (any printer there)` })),
    ...status.printers.map((p) => ({
      value: p.name,
      label: `${p.name}${p.location ? ` @ ${p.location}` : ""}${p.loaded_material ? ` · ${p.loaded_material} loaded` : ""}`,
    })),
  ];
  const ready = where && material && quality && !sending;
  const state = job?.state ?? result?.state;

  return (
    <div className="space-y-3">
      <p className="text-xs leading-relaxed text-ink-dim">
        Sends the generated enclosure to print-warden {status.version ? `(${status.version}) ` : ""}
        which renders it, slices it for the printer and queues it. The print
        starts only from the warden&apos;s phone notification — nothing here starts it.
      </p>

      <div className="grid grid-cols-2 gap-2">
        <label className="space-y-1">
          <FieldLabel>where</FieldLabel>
          <select aria-label="where" value={where} onChange={(e) => selectWhere(e.target.value)} className={SELECT_CLASS}>
            {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
        <label className="space-y-1">
          <FieldLabel>material</FieldLabel>
          <select aria-label="material" value={material} onChange={(e) => setMaterial(e.target.value)} className={SELECT_CLASS} disabled={!materials.length}>
            {materials.map((m) => (
              <option key={m} value={m}>{m}{loaded.includes(m) ? " (loaded)" : ""}</option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <FieldLabel>quality</FieldLabel>
          <select aria-label="quality" value={quality} onChange={(e) => setQuality(e.target.value)} className={SELECT_CLASS} disabled={!qualities.length}>
            {qualities.map((q) => <option key={q} value={q}>{q}</option>)}
          </select>
        </label>
        <label className="space-y-1">
          <FieldLabel>copies</FieldLabel>
          <Input
            aria-label="copies"
            type="number" min={1} max={20} value={copies}
            onChange={(e) => setCopies(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
            className="text-xs"
          />
        </label>
      </div>

      <details className="text-xs">
        <summary className="cursor-pointer text-ink-dim hover:text-ink">Fit tunables</summary>
        <div className="mt-2 grid grid-cols-2 gap-2">
          {TUNABLE_FIELDS.map((f) => (
            <label key={f.key} className="space-y-1">
              <FieldLabel>{f.label}</FieldLabel>
              <Input
                aria-label={f.key}
                type="number" min={0} step={f.step} value={tunables[f.key]}
                onChange={(e) => setTunables({ ...tunables, [f.key]: e.target.value })}
                className="text-xs"
              />
            </label>
          ))}
        </div>
        <p className="mt-1 text-[11px] text-ink-faint">
          Applied by the warden as OpenSCAD <code>-D</code> overrides; only values you change are sent.
        </p>
      </details>

      {material && loaded.length > 0 && !loaded.includes(material) && (
        <div className="rounded-md bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-200 ring-1 ring-amber-500/30">
          {loaded.join(", ")} is loaded there; the warden will slice for {material} but will not start until it matches.
        </div>
      )}

      <Button variant="primary" onClick={handleSend} disabled={!ready}>
        {sending ? "Sending…" : result ? "Sent ✓ — send again" : "Send to print-warden →"}
      </Button>

      {sendError && (
        <div className="rounded-md bg-rose-500/10 px-2 py-1.5 text-xs text-rose-200 ring-1 ring-rose-500/30">
          {sendError}
        </div>
      )}

      {result && (
        <div className="space-y-2 rounded-md border border-line bg-surface-2/40 p-2 text-xs">
          <div className="flex items-start gap-3">
            {(job?.preview_url ?? result.preview_url) && (
              <img
                src={job?.preview_url ?? result.preview_url ?? undefined}
                alt="sliced plate preview"
                className="h-24 w-24 shrink-0 rounded-md object-contain bg-surface-1"
              />
            )}
            <div className="min-w-0 flex-1 space-y-0.5">
              <div className="text-ink">
                Job <code>{result.job_id}</code> on <span className="font-mono">{result.printer}</span>
                {result.routed && <span className="text-ink-faint"> (routed)</span>}
              </div>
              <div className="text-ink-dim">
                {result.material} · {result.quality}
                {(job?.est_human ?? result.est_human) ? ` · est ${job?.est_human ?? result.est_human}` : ""}
                {result.filament_g != null ? ` · ${result.filament_g} g` : ""}
              </div>
              <div className="text-ink-dim">
                state: <span className="font-mono text-ink">{state}</span>
                {job && (job.can_start
                  ? <span className="text-emerald-300"> · can start</span>
                  : job.blockers.length > 0 && <span className="text-amber-200"> · waiting: {job.blockers.join("; ")}</span>)}
              </div>
            </div>
          </div>
          {(job?.slice_blockers ?? result.slice_blockers).length > 0 && (
            <div className="rounded-md bg-rose-500/10 px-2 py-1 text-[11px] text-rose-200 ring-1 ring-rose-500/30">
              Blocked until waived on the warden: {(job?.slice_blockers ?? result.slice_blockers).join("; ")}
            </div>
          )}
          {(job?.warnings ?? result.warnings).length > 0 && (
            <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-amber-200/90">
              {(job?.warnings ?? result.warnings).map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          )}
          <p className="text-[11px] text-ink-faint">{result.starts}.</p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Search tab
// ---------------------------------------------------------------------------

function SearchTab({ boardLibraryId, boardName }: { boardLibraryId: string; boardName: string }) {
  const [refinement, setRefinement] = useState("");
  const [response, setResponse] = useState<EnclosureSearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inflightRef = useRef<{ cancelled: boolean } | null>(null);

  // Fire one initial search on mount so the user sees results immediately.
  useEffect(() => {
    void runSearch("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function runSearch(extra: string) {
    // Cancel any in-flight previous search so a stale response can't
    // overwrite a newer one when the user clicks Search rapidly.
    if (inflightRef.current) inflightRef.current.cancelled = true;
    const ticket = { cancelled: false };
    inflightRef.current = ticket;
    setSearching(true);
    setError(null);
    try {
      const r = await api.enclosureSearch({
        library_id: boardLibraryId,
        query: extra.trim() || undefined,
      });
      if (ticket.cancelled) return;
      setResponse(r);
    } catch (e) {
      if (ticket.cancelled) return;
      const msg = e instanceof ApiError ? `${e.status}: ${e.message}` :
        e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      if (!ticket.cancelled) setSearching(false);
    }
  }

  // Cleanup on unmount: cancel any in-flight search so a late response
  // doesn't write into an unmounted component.
  useEffect(() => () => {
    if (inflightRef.current) inflightRef.current.cancelled = true;
  }, []);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    void runSearch(refinement);
  }

  const sources: EnclosureSourceStatus[] = response?.sources ?? [];
  const anyAvailable = sources.some((s) => s.available);
  const results: EnclosureHit[] = response?.results ?? [];

  return (
    <div className="space-y-3">
      <form onSubmit={onSubmit} className="space-y-1">
        <FieldLabel>refinement</FieldLabel>
        <div className="flex gap-2">
          <Input
            type="text"
            value={refinement}
            onChange={(e) => setRefinement(e.target.value)}
            placeholder={`e.g. battery, screw mount, slim`}
            className="flex-1 text-xs"
          />
          <Button type="submit" disabled={searching}>
            {searching ? "Searching…" : "Search"}
          </Button>
        </div>
        <p className="text-[11px] text-ink-faint">
          Query: <code className="text-ink-dim">
            {response?.query || `${boardName} enclosure${refinement.trim() ? ` ${refinement.trim()}` : ""}`}
          </code>
        </p>
      </form>

      {sources.length > 0 && (
        <div className="space-y-1">
          {sources.map((s) => (
            <div
              key={s.source}
              className={`rounded-md px-2 py-1 text-[11px] ring-1 ${
                s.available
                  ? "bg-emerald-500/10 text-emerald-200 ring-emerald-500/30"
                  : "bg-amber-500/10 text-amber-200 ring-amber-500/30"
              }`}
            >
              <span className="font-mono">{s.source}</span>
              {s.available ? " · available" : ` · unavailable: ${s.reason ?? "unknown"}`}
              {s.configure_hint && !s.available && (
                <div className="mt-0.5 text-[10px] text-amber-200/80">{s.configure_hint}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="rounded-md bg-rose-500/10 px-2 py-1.5 text-xs text-rose-200 ring-1 ring-rose-500/30">
          {error}
        </div>
      )}

      {!anyAvailable && response && (
        <div className="rounded-md border border-line bg-surface-2/40 px-3 py-2 text-xs text-ink-dim">
          No search source is configured. Set the env var listed in the source
          status above and restart the studio API to enable search.
        </div>
      )}

      {results.length > 0 && (
        <ul className="space-y-2">
          {results.map((r) => (
            <li
              key={`${r.source}:${r.id}`}
              className="rounded-md border border-line bg-surface-2/40 p-2"
            >
              <div className="flex items-start gap-3">
                {r.thumbnail_url && (
                  <a href={r.model_url} target="_blank" rel="noreferrer noopener">
                    <img
                      src={r.thumbnail_url}
                      alt=""
                      className="h-20 w-20 shrink-0 rounded-md object-cover"
                      loading="lazy"
                    />
                  </a>
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <a
                      href={r.model_url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="text-sm text-ink hover:underline"
                    >
                      {r.title}
                    </a>
                    <span className="text-[11px] text-ink-faint">{r.source}</span>
                  </div>
                  <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-faint">
                    {r.creator && <span>by {r.creator}</span>}
                    {r.likes != null && <span>♥ {r.likes}</span>}
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {!searching && response && results.length === 0 && anyAvailable && (
        <div className="text-xs text-ink-faint">
          No matches for <code className="rounded-md bg-surface-2 px-1">{response.query}</code>.
          Try a different refinement.
        </div>
      )}
    </div>
  );
}
