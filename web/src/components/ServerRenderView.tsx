import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import type { Design } from "../types/api";
import { api, ApiError } from "../api/client";
import { Button } from "./ui";

interface Status {
  available: boolean;
  reason: string | null;
}

/**
 * Server-rendered SVG preview (schematic or placed PCB). Both pipelines
 * run kicad-cli on the server and are gated on tool availability, so the
 * view probes status first and renders only on explicit request -- a
 * render can take up to two minutes.
 */
export function ServerRenderView({ design, kind }: { design: Design; kind: "schematic" | "pcb" }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [rendering, setRendering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const probe = kind === "schematic" ? api.kicadRenderStatus() : api.kicadPcbRenderStatus();
    probe
      .then((s) => { if (!cancelled) setStatus({ available: s.available, reason: s.reason }); })
      .catch((e) => {
        if (!cancelled) setStatus({ available: false, reason: e instanceof Error ? e.message : String(e) });
      });
    return () => { cancelled = true; };
  }, [kind]);

  useEffect(() => {
    setUrl((u) => {
      if (u) URL.revokeObjectURL(u);
      return null;
    });
    setError(null);
  }, [design, kind]);

  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  async function renderNow() {
    setRendering(true);
    setError(null);
    try {
      const svg = kind === "schematic" ? await api.kicadRender(design) : await api.kicadPcbRender(design);
      setUrl(URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" })));
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : e instanceof Error ? e.message : String(e));
    } finally {
      setRendering(false);
    }
  }

  const label = kind === "schematic" ? "schematic" : "placed board";

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs text-ink-faint">
          {status === null
            ? "Checking server tools…"
            : status.available
              ? `Server-side render of the ${label} via kicad-cli.`
              : null}
        </div>
        {status?.available && (
          <Button variant="primary" disabled={rendering} onClick={renderNow}>
            <RefreshCw className={`h-3.5 w-3.5 ${rendering ? "animate-spin" : ""}`} />
            {rendering ? "Rendering…" : url ? "Re-render" : `Render ${label}`}
          </Button>
        )}
      </div>

      {status !== null && !status.available && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">
          <div className="font-semibold">Preview unavailable on this server</div>
          <div className="mt-1">{status.reason}</div>
          <div className="mt-2 text-amber-200/80">
            The {label} preview needs the KiCad toolchain server-side; the
            <code className="mx-1 font-mono">-full</code> Docker image includes it.
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-200">
          <div className="font-semibold">Render failed</div>
          <div className="mt-1 whitespace-pre-wrap">{error}</div>
        </div>
      )}

      {url ? (
        <div className="overflow-auto rounded-lg bg-white p-2 ring-1 ring-line">
          <img src={url} alt={`${label} preview`} className="w-full" />
        </div>
      ) : (
        status?.available && !rendering && (
          <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-line text-sm text-ink-ghost">
            Render to preview the {label}.
          </div>
        )
      )}
    </div>
  );
}
