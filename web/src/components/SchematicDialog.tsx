/**
 * Schematic export dialog. Two paths:
 *  - Download a SKiDL Python script the user runs locally to produce a
 *    `<design_id>.kicad_sch` (always available).
 *  - Render an inline SVG preview, when the server has `kicad-cli` + SKiDL
 *    installed. The preview is feature-gated the same way the agent and
 *    fleet features are: probe `/design/kicad/render/status` and degrade
 *    to a notice when the tools are missing.
 */
import { useEffect, useRef, useState } from "react";
import { api, ApiError, kicadRoute } from "../api/client";
import type {
  Design,
  FabStatus,
  KicadPcbStatus,
  KicadRenderStatus,
  KicadRouteStatus,
} from "../types/api";
import { Button, Dialog } from "./ui";

interface Props {
  design: Design;
  onClose: () => void;
}

function formatError(e: unknown): string {
  if (e instanceof ApiError) {
    const detail = (e.body as { detail?: unknown } | undefined)?.detail;
    return `${e.status}: ${typeof detail === "string" ? detail : e.message}`;
  }
  return e instanceof Error ? e.message : String(e);
}

function saveBlob(part: BlobPart, filename: string, type: string) {
  const url = URL.createObjectURL(new Blob([part], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function SchematicDialog({ design, onClose }: Props) {
  const [downloading, setDownloading] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [renderStatus, setRenderStatus] = useState<KicadRenderStatus | null>(null);
  const [rendering, setRendering] = useState(false);
  const [svgUrl, setSvgUrl] = useState<string | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);

  const [pcbStatus, setPcbStatus] = useState<KicadPcbStatus | null>(null);
  const [pcbDownloading, setPcbDownloading] = useState(false);
  const [pcbDownloaded, setPcbDownloaded] = useState(false);
  const [pcbError, setPcbError] = useState<string | null>(null);

  const [fabStatus, setFabStatus] = useState<FabStatus | null>(null);
  const [fabBusy, setFabBusy] = useState<string | null>(null);
  const [fabError, setFabError] = useState<string | null>(null);
  const [fabRouted, setFabRouted] = useState(false);

  const [routeStatus, setRouteStatus] = useState<KicadRouteStatus | null>(null);
  const [routing, setRouting] = useState(false);
  const [routeLog, setRouteLog] = useState("");
  const [routeKey, setRouteKey] = useState<string | null>(null);
  const [routeError, setRouteError] = useState<string | null>(null);
  const routeLogRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    let live = true;
    api
      .kicadRenderStatus()
      .then((s) => live && setRenderStatus(s))
      .catch(() => live && setRenderStatus({
        available: false, kicad_cli: false, skidl: false, png: false,
        reason: "render status unavailable",
      }));
    api
      .kicadPcbStatus()
      .then((s) => live && setPcbStatus(s))
      .catch(() => live && setPcbStatus({
        available: false, footprints: false, symbols: false,
        reason: "pcb status unavailable",
      }));
    api
      .fabStatus()
      .then((s) => live && setFabStatus(s))
      .catch(() => live && setFabStatus({
        bom: true, cpl: false, gerbers: false, route: false, route_reason: null,
        kicad_cli: false, footprints: false, reason: "fab status unavailable",
      }));
    api
      .kicadRouteStatus()
      .then((s) => live && setRouteStatus(s))
      .catch(() => live && setRouteStatus({
        available: false, pcbnew: null, java: null, freerouting_jar: null,
        reason: "route status unavailable",
      }));
    return () => {
      live = false;
    };
  }, []);

  // Keep the route log scrolled to the newest line.
  useEffect(() => {
    const el = routeLogRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [routeLog]);

  // Revoke the object URL when it's replaced or the dialog unmounts.
  useEffect(() => {
    return () => {
      if (svgUrl) URL.revokeObjectURL(svgUrl);
    };
  }, [svgUrl]);

  async function handleDownload() {
    setDownloading(true);
    setDownloaded(false);
    setError(null);
    try {
      const py = await api.kicadSchematic(design);
      const blob = new Blob([py], { type: "text/x-python" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${design.id ?? "design"}.skidl.py`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setDownloaded(true);
    } catch (e) {
      setError(formatError(e));
    } finally {
      setDownloading(false);
    }
  }

  async function handleRender() {
    setRendering(true);
    setRenderError(null);
    try {
      const svg = await api.kicadRender(design);
      const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
      setSvgUrl(url);
    } catch (e) {
      setRenderError(formatError(e));
    } finally {
      setRendering(false);
    }
  }

  async function handleDownloadPcb() {
    setPcbDownloading(true);
    setPcbDownloaded(false);
    setPcbError(null);
    try {
      const board = await api.kicadPcb(design);
      const url = URL.createObjectURL(new Blob([board], { type: "application/octet-stream" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${design.id ?? "design"}.kicad_pcb`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setPcbDownloaded(true);
    } catch (e) {
      setPcbError(formatError(e));
    } finally {
      setPcbDownloading(false);
    }
  }

  const id = design.id ?? "design";

  async function handleRoute() {
    setRouting(true);
    setRouteLog("");
    setRouteKey(null);
    setRouteError(null);
    try {
      for await (const event of kicadRoute(design)) {
        if (event.type === "log") {
          setRouteLog((prev) => prev + event.data);
        } else if (event.type === "done") {
          if (event.ok) {
            setRouteKey(event.cache_key);
          } else {
            setRouteError("Routing completed without a routed board — see the log.");
          }
        }
      }
    } catch (e) {
      setRouteError(formatError(e));
    } finally {
      setRouting(false);
    }
  }

  async function handleDownloadRouted() {
    if (!routeKey) return;
    setRouteError(null);
    try {
      saveBlob(
        await api.kicadRoutedBoard(routeKey),
        `${id}-routed.kicad_pcb`,
        "application/octet-stream",
      );
    } catch (e) {
      setRouteError(formatError(e));
    }
  }

  async function handleFab(
    kind: string,
    fetcher: () => Promise<string | Blob>,
    filename: string,
    type: string,
  ) {
    setFabBusy(kind);
    setFabError(null);
    try {
      saveBlob(await fetcher(), filename, type);
    } catch (e) {
      setFabError(formatError(e));
    } finally {
      setFabBusy(null);
    }
  }

  return (
    <Dialog
      title="KiCad export"
      subtitle="Preview the schematic, download a SKiDL script, or export a PCB board."
      onClose={onClose}
      maxWidth="max-w-3xl"
    >
      <div className="space-y-4 text-sm text-ink-dim">
        {/* --- Inline preview --------------------------------------- */}
        <section className="space-y-2">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
            Preview
          </div>
          {renderStatus === null ? (
            <div className="text-xs text-ink-faint">Checking renderer…</div>
          ) : renderStatus.available ? (
            <>
              <Button variant="primary" onClick={handleRender} disabled={rendering}>
                {rendering ? "Rendering…" : svgUrl ? "Re-render" : "Render schematic"}
              </Button>
              {svgUrl && (
                <div className="overflow-auto rounded-md border border-line bg-white p-2">
                  <img src={svgUrl} alt="rendered schematic" className="mx-auto block" />
                </div>
              )}
              {renderError && (
                <div className="rounded-md bg-rose-500/10 px-2 py-1.5 text-xs text-rose-200 ring-1 ring-rose-500/30">
                  {renderError}
                </div>
              )}
            </>
          ) : (
            <div className="rounded-md border border-line bg-surface-2/40 px-2 py-1.5 text-xs text-ink-dim">
              Inline preview needs <code className="text-ink">kicad-cli</code> and{" "}
              <code className="text-ink">skidl</code> on the server.
              {renderStatus.reason && (
                <span className="text-ink-faint"> ({renderStatus.reason})</span>
              )}{" "}
              Download the script below and render it locally instead.
            </div>
          )}
        </section>

        {/* --- Download the SKiDL script ----------------------------- */}
        <section className="space-y-3 border-t border-line pt-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
            Download script
          </div>
          <p className="text-xs leading-relaxed text-ink-dim">
            A self-contained <code className="text-ink">.skidl.py</code> file.
            Run it with{" "}
            <a
              href="https://devbisme.github.io/skidl/"
              target="_blank"
              rel="noreferrer noopener"
              className="text-accent-300 hover:underline"
            >
              SKiDL
            </a>
            {" "}installed:
          </p>
          <pre className="overflow-x-auto rounded-lg bg-surface-0 p-2 font-mono text-[12px] leading-relaxed text-ink ring-1 ring-line">
{`pip install skidl
python ${design.id ?? "design"}.skidl.py
# produces ${design.id ?? "design"}.kicad_sch in the cwd`}
          </pre>
          <p className="text-[11px] text-ink-faint">
            Components without a <code>kicad:</code> mapping in the studio
            library render as a generic 4-pin connector with a TODO
            comment; you can either patch the .py before running or fill
            in the library YAML and re-export. Pin-name remaps from
            each component's <code>kicad.pin_map</code> are baked into
            the script (e.g., the BME280's VCC role becomes VDD on the
            schematic to match the Bosch symbol's pin name).
          </p>
          <Button variant="primary" onClick={handleDownload} disabled={downloading}>
            {downloading
              ? "Generating…"
              : downloaded
                ? "Downloaded ✓ — generate again"
                : "Download .skidl.py →"}
          </Button>
          {error && (
            <div className="rounded-md bg-rose-500/10 px-2 py-1.5 text-xs text-rose-200 ring-1 ring-rose-500/30">
              {error}
            </div>
          )}
        </section>

        {/* --- PCB board (.kicad_pcb) -------------------------------- */}
        <section className="space-y-2 border-t border-line pt-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
            PCB board
          </div>
          <p className="text-xs leading-relaxed text-ink-dim">
            A <code className="text-ink">.kicad_pcb</code> with every
            part placed on a grid and pads wired to nets — open it in KiCad's
            PCB editor with a full ratsnest and route it yourself, or
            autoroute it below.
          </p>
          {pcbStatus === null ? (
            <div className="text-xs text-ink-faint">Checking…</div>
          ) : pcbStatus.available ? (
            <Button variant="primary" onClick={handleDownloadPcb} disabled={pcbDownloading}>
              {pcbDownloading
                ? "Generating…"
                : pcbDownloaded
                  ? "Downloaded ✓ — generate again"
                  : "Download .kicad_pcb →"}
            </Button>
          ) : (
            <div className="rounded-md border border-line bg-surface-2/40 px-2 py-1.5 text-xs text-ink-dim">
              The board export needs the KiCad footprint + symbol libraries
              on the server.
              {pcbStatus.reason && (
                <span className="text-ink-faint"> ({pcbStatus.reason})</span>
              )}
            </div>
          )}
          {pcbError && (
            <div className="rounded-md bg-rose-500/10 px-2 py-1.5 text-xs text-rose-200 ring-1 ring-rose-500/30">
              {pcbError}
            </div>
          )}
        </section>

        {/* --- Autoroute (Freerouting) ------------------------------- */}
        <section className="space-y-2 border-t border-line pt-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
            Autoroute
          </div>
          <p className="text-xs leading-relaxed text-ink-dim">
            Route the board with Freerouting on the server and download the
            routed <code className="text-ink">.kicad_pcb</code>. Results
            are cached — re-routing an unchanged design is instant.
          </p>
          {routeStatus === null ? (
            <div className="text-xs text-ink-faint">Checking…</div>
          ) : routeStatus.available ? (
            <>
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" onClick={handleRoute} disabled={routing}>
                  {routing ? "Routing…" : routeKey ? "Route again" : "Route board"}
                </Button>
                {routeKey && (
                  <button
                    onClick={handleDownloadRouted}
                    className="rounded-md bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-200 ring-1 ring-emerald-500/30 transition-colors hover:bg-emerald-500/20"
                  >
                    Download routed .kicad_pcb →
                  </button>
                )}
              </div>
              {(routing || routeLog) && (
                <pre
                  ref={routeLogRef}
                  className="max-h-40 overflow-y-auto rounded-lg bg-surface-0 p-2 font-mono text-[12px] leading-relaxed text-ink-dim ring-1 ring-line"
                >
                  {routeLog || "Starting Freerouting…"}
                </pre>
              )}
            </>
          ) : (
            <div className="rounded-md border border-line bg-surface-2/40 px-2 py-1.5 text-xs text-ink-dim">
              Autorouting needs the route toolchain on the server (pcbnew,
              Java, and the Freerouting jar) — use the{" "}
              <code className="text-ink">-pcb</code> image variant.
              {routeStatus.reason && (
                <span className="text-ink-faint"> ({routeStatus.reason})</span>
              )}
            </div>
          )}
          {routeError && (
            <div className="rounded-md bg-rose-500/10 px-2 py-1.5 text-xs text-rose-200 ring-1 ring-rose-500/30">
              {routeError}
            </div>
          )}
        </section>

        {/* --- Fab outputs (BOM / CPL / Gerbers) --------------------- */}
        <section className="space-y-2 border-t border-line pt-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
            Fab outputs
          </div>
          <p className="text-xs leading-relaxed text-ink-dim">
            BOM + pick-and-place (CPL) for assembly, and a Gerber/drill bundle
            for a board house. Check <em>Routed</em> to autoroute before
            exporting; unrouted Gerbers carry pads but no traces.
          </p>
          <label
            className={`flex w-fit items-center gap-2 text-xs ${
              fabStatus?.route ? "text-ink-dim" : "text-ink-ghost"
            }`}
            title={
              fabStatus && !fabStatus.route
                ? fabStatus.route_reason ?? "Needs the route toolchain on the server"
                : undefined
            }
          >
            <input
              type="checkbox"
              checked={fabRouted}
              disabled={!fabStatus?.route}
              onChange={(e) => setFabRouted(e.target.checked)}
            />
            Routed (autoroute before export)
          </label>
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => handleFab("bom", () => api.fabBom(design), `${id}-bom.csv`, "text/csv")}
              disabled={fabBusy !== null}
            >
              {fabBusy === "bom" ? "…" : "BOM .csv"}
            </Button>
            <Button
              onClick={() => handleFab("cpl", () => api.fabCpl(design), `${id}-cpl.csv`, "text/csv")}
              disabled={fabBusy !== null || !fabStatus?.cpl}
              title={fabStatus && !fabStatus.cpl ? "Needs the footprint libraries on the server" : undefined}
            >
              {fabBusy === "cpl" ? "…" : "CPL .csv"}
            </Button>
            <Button
              variant="primary"
              onClick={() => handleFab("package", () => api.fabPackage(design, fabRouted), `${id}-fab.zip`, "application/zip")}
              disabled={fabBusy !== null || !fabStatus?.gerbers}
              title={fabStatus && !fabStatus.gerbers ? "Needs kicad-cli + the libraries on the server" : undefined}
            >
              {fabBusy === "package"
                ? fabRouted ? "Routing + generating…" : "Generating…"
                : "Fab package .zip →"}
            </Button>
          </div>
          {fabStatus && !fabStatus.gerbers && (
            <div className="text-[11px] text-ink-faint">
              Gerbers need <code className="text-ink-dim">kicad-cli</code> on the server
              {fabStatus.reason && <span> ({fabStatus.reason})</span>}. BOM is always available.
            </div>
          )}
          {fabError && (
            <div className="rounded-md bg-rose-500/10 px-2 py-1.5 text-xs text-rose-200 ring-1 ring-rose-500/30">
              {fabError}
            </div>
          )}
        </section>
      </div>
    </Dialog>
  );
}
