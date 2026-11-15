/**
 * Schematic and PCB dialog, one tab per output: the drawn .kicad_sch with an
 * inline preview, the SKiDL script (always available), the placed .kicad_pcb
 * with fab outputs, and the Freerouting autoroute. Each server-side output is
 * feature-gated the way the agent and fleet features are: probe its status
 * endpoint and degrade to one notice on the tab when the tools are missing.
 */
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api, ApiError, kicadRoute } from "../api/client";
import type {
  DrcSummary,
  Design,
  FabStatus,
  KicadPcbStatus,
  KicadRenderStatus,
  KicadRouteStatus,
  KicadSchStatus,
} from "../types/api";
import { Button, Code, Dialog, Input, Notice, Section, Tabs } from "./ui";
import { RouteDrcReport } from "./RouteDrcReport";

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

type Tab = "schematic" | "skidl" | "pcb" | "route";

export function SchematicDialog({ design, onClose }: Props) {
  const [tab, setTab] = useState<Tab>("schematic");
  const id = typeof design.id === "string" ? design.id : "design";
  const [downloading, setDownloading] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [schStatus, setSchStatus] = useState<KicadSchStatus | null>(null);
  const [schDownloading, setSchDownloading] = useState(false);
  const [schDownloaded, setSchDownloaded] = useState(false);
  const [schError, setSchError] = useState<string | null>(null);

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
  const [routeDrc, setRouteDrc] = useState<DrcSummary | { error: string } | null | undefined>(undefined);
  const [viaCosts, setViaCosts] = useState("");
  const [keepouts, setKeepouts] = useState("");
  const routeLogRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    let live = true;
    api
      .kicadRenderStatus()
      .then((s) => live && setRenderStatus(s))
      .catch(() => live && setRenderStatus({
        available: false, kicad_cli: false, symbols: false, png: false,
        reason: "render status unavailable",
      }));
    api
      .kicadSchStatus()
      .then((s) => live && setSchStatus(s))
      .catch(() => live && setSchStatus({
        available: false, symbol_dir: null, reason: "schematic status unavailable",
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

  async function handleDownloadSch() {
    setSchDownloading(true);
    setSchDownloaded(false);
    setSchError(null);
    try {
      saveBlob(await api.kicadSch(design), `${design.id ?? "design"}.kicad_sch`, "application/octet-stream");
      setSchDownloaded(true);
    } catch (e) {
      setSchError(formatError(e));
    } finally {
      setSchDownloading(false);
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

  async function handleRoute() {
    setRouting(true);
    setRouteLog("");
    setRouteKey(null);
    setRouteError(null);
    setRouteDrc(undefined);
    try {
      const params = {
        viaCosts: viaCosts.trim() ? Number(viaCosts) : undefined,
        keepouts: keepouts.split(/[;\n]/).map((k) => k.trim()).filter(Boolean),
      };
      for await (const event of kicadRoute(design, params)) {
        if (event.type === "log") {
          setRouteLog((prev) => prev + event.data);
        } else if (event.type === "done") {
          if (event.ok) {
            setRouteKey(event.cache_key);
            setRouteDrc(event.drc);
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

  const tabs: { id: Tab; label: ReactNode }[] = [
    { id: "schematic", label: <TabLabel missing={schStatus?.available === false || renderStatus?.available === false}>Schematic</TabLabel> },
    { id: "skidl", label: "SKiDL script" },
    { id: "pcb", label: <TabLabel missing={pcbStatus?.available === false}>PCB board</TabLabel> },
    { id: "route", label: <TabLabel missing={routeStatus?.available === false}>Autoroute</TabLabel> },
  ];

  const footer: Record<Tab, ReactNode> = {
    schematic: (
      <>
        <Button onClick={handleRender} disabled={rendering || !renderStatus?.available}>
          {rendering ? "Rendering…" : svgUrl ? "Re-render" : "Render schematic"}
        </Button>
        <Button variant="primary" onClick={handleDownloadSch} disabled={schDownloading || !schStatus?.available}>
          {schDownloading ? "Writing…" : "Download .kicad_sch"}
        </Button>
      </>
    ),
    skidl: (
      <Button variant="primary" onClick={handleDownload} disabled={downloading}>
        {downloading ? "Generating…" : "Download .skidl.py"}
      </Button>
    ),
    pcb: (
      <Button variant="primary" onClick={handleDownloadPcb} disabled={pcbDownloading || !pcbStatus?.available}>
        {pcbDownloading ? "Generating…" : "Download .kicad_pcb"}
      </Button>
    ),
    route: (
      <>
        {routeKey && <Button onClick={handleDownloadRouted}>Download routed .kicad_pcb</Button>}
        <Button variant="primary" onClick={handleRoute} disabled={routing || !routeStatus?.available}>
          {routing ? "Routing…" : routeKey ? "Route again" : "Route board"}
        </Button>
      </>
    ),
  };

  const footerNote: Record<Tab, ReactNode> = {
    schematic: schDownloaded ? <>Downloaded <Code>{id}.kicad_sch</Code></> : null,
    skidl: downloaded ? <>Downloaded <Code>{id}.skidl.py</Code></> : null,
    pcb: pcbDownloaded ? <>Downloaded <Code>{id}.kicad_pcb</Code></> : null,
    route: routeKey ? "Routed. Results are cached per design." : null,
  };

  return (
    <Dialog
      title="Schematic and PCB"
      subtitle={<>KiCad 8 files for <span className="font-mono">{id}</span>, drawn by the studio.</>}
      onClose={onClose}
      maxWidth="max-w-3xl"
      footer={footer[tab]}
      footerNote={footerNote[tab]}
    >
      <Tabs label="KiCad outputs" tabs={tabs} value={tab} onChange={setTab} className="-mx-5 -mt-4 mb-4 px-2" />

      {tab === "schematic" && (
        <div className="space-y-3 text-xs leading-relaxed text-ink-dim">
          <p>
            A KiCad 8 <Code>.kicad_sch</Code> drawn by the studio:
            the board with every pin labelled or flagged, peripherals beside it,
            and each subcircuit drawn as a circuit where its library entry has a
            layout. Symbols are embedded, so it opens with no library setup.
          </p>
          {(schStatus === null || renderStatus === null) && (
            <div className="text-ink-faint">Checking server tools…</div>
          )}
          {schStatus?.available === false ? (
            <Notice tone="amber" title="Schematic export is unavailable on this server">
              <div className="mt-1">
                Writing the schematic needs the KiCad symbol libraries on the server.
                {schStatus.reason && <> ({schStatus.reason})</>}{" "}
                The SKiDL script works without them.
              </div>
            </Notice>
          ) : renderStatus?.available === false && (
            <Notice tone="amber" title="Schematic preview is unavailable on this server">
              <div className="mt-1">
                The inline preview needs <Code>kicad-cli</Code> and the KiCad symbol
                libraries on the server.
                {renderStatus.reason && <> ({renderStatus.reason})</>}{" "}
                Open the download in KiCad, or run the SKiDL script and render it locally instead.
              </div>
            </Notice>
          )}
          {svgUrl && (
            <div className="overflow-auto rounded-md border border-line bg-white p-2">
              <img src={svgUrl} alt="rendered schematic" className="mx-auto block" />
            </div>
          )}
          {renderError && <ErrorBanner>{renderError}</ErrorBanner>}
          {schError && <ErrorBanner>{schError}</ErrorBanner>}
        </div>
      )}

      {tab === "skidl" && (
        <div className="space-y-3 text-xs leading-relaxed text-ink-dim">
          <p>
            A self-contained <Code>.skidl.py</Code> file.
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
python ${id}.skidl.py
# produces ${id}.kicad_sch in the cwd`}
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
          {error && <ErrorBanner>{error}</ErrorBanner>}
        </div>
      )}

      {tab === "pcb" && (
        <div className="space-y-3 text-xs leading-relaxed text-ink-dim">
          <p>
            A <Code>.kicad_pcb</Code> with every part placed on a grid and pads
            wired to nets. Open it in KiCad's PCB editor with a full ratsnest
            and route it yourself, or autoroute it on the Autoroute tab.
          </p>
          {pcbStatus === null && <div className="text-ink-faint">Checking server tools…</div>}
          {pcbStatus?.available === false && (
            <Notice tone="amber" title="Board export is unavailable on this server">
              <div className="mt-1">
                The board export needs the KiCad footprint and symbol libraries on the server.
                {pcbStatus.reason && <> ({pcbStatus.reason})</>}
                {fabStatus && !fabStatus.gerbers && (
                  <> Gerbers also need <Code>kicad-cli</Code>{fabStatus.reason && <> ({fabStatus.reason})</>}. The BOM is always available.</>
                )}
              </div>
            </Notice>
          )}
          {pcbError && <ErrorBanner>{pcbError}</ErrorBanner>}

          <Section title="Fab outputs">
            <div className="space-y-2">
              <p>
                BOM and pick-and-place (CPL) for assembly, and a Gerber and drill bundle
                for a board house. Check <em>Routed</em> to autoroute before
                exporting; unrouted Gerbers carry pads but no traces.
              </p>
              <label
                className={`flex w-fit items-center gap-2 ${fabStatus?.route ? "text-ink-dim" : "text-ink-ghost"}`}
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
                  onClick={() => handleFab("package", () => api.fabPackage(design, fabRouted), `${id}-fab.zip`, "application/zip")}
                  disabled={fabBusy !== null || !fabStatus?.gerbers}
                  title={fabStatus && !fabStatus.gerbers ? "Needs kicad-cli and the libraries on the server" : undefined}
                >
                  {fabBusy === "package"
                    ? fabRouted ? "Routing and generating…" : "Generating…"
                    : "Fab package .zip"}
                </Button>
              </div>
              {pcbStatus?.available && fabStatus && !fabStatus.gerbers && (
                <div className="text-[11px] text-ink-faint">
                  Gerbers need <Code>kicad-cli</Code> on the server
                  {fabStatus.reason && <span> ({fabStatus.reason})</span>}. The BOM is always available.
                </div>
              )}
              {fabError && <ErrorBanner>{fabError}</ErrorBanner>}
            </div>
          </Section>
        </div>
      )}

      {tab === "route" && (
        <div className="space-y-3 text-xs leading-relaxed text-ink-dim">
          <p>
            Route the board with Freerouting on the server and download the
            routed <Code>.kicad_pcb</Code>. Results are cached, so re-routing
            an unchanged design is instant.
          </p>
          {routeStatus === null && <div className="text-ink-faint">Checking server tools…</div>}
          {routeStatus?.available === false && (
            <Notice tone="amber" title="Autorouting is unavailable on this server">
              <div className="mt-1">
                It needs the route toolchain on the server: <Code>pcbnew</Code>, Java
                and the Freerouting jar. The <Code>-pcb</Code> image variant has all three.
                {routeStatus.reason && <> ({routeStatus.reason})</>}
              </div>
            </Notice>
          )}
          {routeStatus?.available && (
            <>
              <div className="grid grid-cols-[4.5rem_1fr] items-center gap-x-2 gap-y-1.5">
                <label htmlFor="route-via-costs" title="Higher trades vias for longer tracks; empty is Freerouting's default">Via cost</label>
                <Input
                  compact
                  id="route-via-costs"
                  inputMode="numeric"
                  value={viaCosts}
                  onChange={(e) => setViaCosts(e.target.value.replace(/[^0-9]/g, ""))}
                  placeholder="default"
                  className="w-24"
                />
                <label htmlFor="route-keepouts" title="x,y,w,h in the board's mm (open the placed .kicad_pcb to read them); add ,tracks or ,vias to keep out only one; separate with ;">Keepouts</label>
                <Input
                  compact
                  mono
                  id="route-keepouts"
                  value={keepouts}
                  onChange={(e) => setKeepouts(e.target.value)}
                  placeholder="x,y,w,h; …"
                />
              </div>
              {(routing || routeLog) && (
                <pre
                  ref={routeLogRef}
                  className="max-h-40 overflow-y-auto rounded-lg bg-surface-0 p-2 font-mono text-[12px] leading-relaxed text-ink-dim ring-1 ring-line"
                >
                  {routeLog || "Starting Freerouting…"}
                </pre>
              )}
              {routeKey && <RouteDrcReport drc={routeDrc} />}
            </>
          )}
          {routeError && <ErrorBanner>{routeError}</ErrorBanner>}
        </div>
      )}
    </Dialog>
  );
}

function TabLabel({ missing, children }: { missing: boolean; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {children}
      {missing && <span role="img" aria-label="needs server setup" className="h-1.5 w-1.5 rounded-full bg-amber-400" />}
    </span>
  );
}

function ErrorBanner({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1.5 text-xs text-rose-200">
      {children}
    </div>
  );
}
