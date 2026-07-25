/**
 * Enclosure dialog (0.8). Two tabs:
 *
 *   Generate — downloads a parametric `.scad` shell built from the
 *              board's enclosure metadata. Same path as the prior
 *              header-button download; just framed in a dialog so it
 *              shares the modal furniture with the search tab.
 *   Search   — relays to /enclosure/search and renders ranked
 *              community-uploaded models. The Search tab is gated on
 *              at least one source being available; when none are
 *              configured, surfaces the per-source configure_hint.
 *
 * The /enclosure/search/status fetch happens lazily on first open of
 * the Search tab so the dialog opens fast.
 */
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type {
  Design,
  EnclosureHit,
  EnclosureSearchResponse,
  EnclosureSourceStatus,
} from "../types/api";
import { Button, Dialog, FieldLabel, Input } from "./ui";

type Tab = "generate" | "search";

interface Props {
  design: Design;
  /** library_id of the design's board, pulled out at call site so the
   *  dialog doesn't have to walk the design dict itself. */
  boardLibraryId: string;
  /** Display name for the search query construction copy. */
  boardName: string;
  onClose: () => void;
}

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
        {(["generate", "search"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-2 transition-colors ${
              tab === t
                ? "border-b-2 border-accent-400 text-ink"
                : "text-ink-dim hover:text-ink"
            }`}
          >
            {t === "generate" ? "Generate (OpenSCAD)" : "Search community models"}
          </button>
        ))}
      </div>

      <div className="text-sm">
        {tab === "generate" ? (
          <GenerateTab design={design} />
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
        for printing. Bottom shell only -- the lid is up to you, for now.
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
