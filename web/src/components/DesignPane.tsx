import { useState, useMemo, useEffect } from "react";
import { Copy, Check, ChevronDown } from "lucide-react";
import type { Design, RenderResponse } from "../types/api";
import { Loading } from "./Status";
import { WiringLegend, WiringView } from "./WiringView";
import { ServerRenderView } from "./ServerRenderView";
import { Chip, Code, Notice } from "./ui";

type Tab = "wiring" | "ascii" | "yaml" | "json" | "schematic" | "pcb";

interface Props {
  design: Design | null;
  render: RenderResponse | null;
  renderError: string | null;
  advancedMode: boolean;
}

export function DesignPane({ design, render, renderError, advancedMode }: Props) {
  const [tab, setTab] = useState<Tab>("wiring");

  useEffect(() => {
    if (!advancedMode && (tab === "schematic" || tab === "pcb")) setTab("wiring");
  }, [advancedMode, tab]);
  const [copied, setCopied] = useState(false);
  const [showDescription, setShowDescription] = useState(false);

  const meta = useMemo(() => (design ? readMeta(design) : null), [design]);

  const content = useMemo(() => {
    return tab === "json"
      ? design
        ? JSON.stringify(design, null, 2)
        : ""
      : tab === "yaml"
        ? render?.yaml ?? ""
        : render?.ascii ?? "";
  }, [tab, design, render]);

  // When a render error is up, the YAML/ASCII tabs are stale (showing the
  // last successful render). The wiring and JSON tabs read design state
  // directly so they stay live regardless of render errors. Treat staleness
  // as "renderError is set AND the visible content was produced by the
  // render endpoint (i.e. ascii or yaml)".
  const tabStale = renderError !== null && (tab === "ascii" || tab === "yaml") && content !== "";

  async function copy() {
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked (insecure context / permissions) -- no-op
    }
  }

  return (
    <section className="@container flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="border-b border-line px-4 py-2.5">
        {meta ? (
          <>
            <div className="flex min-w-0 items-center gap-3">
              <h2 className="min-w-[6rem] truncate text-base font-semibold tracking-tight text-ink">{meta.name}</h2>
              <span className="shrink-0 text-xs"><Code>{meta.id}</Code></span>
              <Chip variant="mcu" className="shrink-0 text-xs">{meta.boardId}</Chip>
              <span
                className="hidden shrink-0 text-xs text-ink-faint @2xl:inline"
                title={`mcu ${meta.mcu}${meta.framework ? `, ${meta.framework}` : ""}`}
              >
                {meta.componentCount} components · {meta.busCount} buses · {meta.connectionCount} connections
              </span>
              {meta.description && (
                <button
                  onClick={() => setShowDescription((v) => !v)}
                  aria-expanded={showDescription}
                  className="ml-auto flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-xs text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
                >
                  Description
                  <ChevronDown className={`h-3 w-3 transition-transform ${showDescription ? "rotate-180" : ""}`} />
                </button>
              )}
            </div>
            {showDescription && meta.description && (
              <p className="mt-1.5 max-w-prose text-sm text-ink-dim">{meta.description}</p>
            )}
          </>
        ) : (
          <div className="text-sm text-ink-faint">No design loaded.</div>
        )}
      </div>

      <div className="flex items-center justify-between border-b border-line pr-2 text-xs">
        <div className="flex">
          {([
            "wiring", "ascii", "yaml", "json",
            ...(advancedMode ? (["schematic", "pcb"] as const) : []),
          ] as Tab[]).map((t) => {
            // Mark ascii/yaml as stale when there's a render error -- those
            // two come from the render endpoint, which is failing. The other
            // tabs read design state directly or render on demand.
            const stale = renderError !== null && (t === "ascii" || t === "yaml");
            return (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-3 py-2 font-medium uppercase tracking-wider transition-colors ${
                  tab === t
                    ? "border-b-2 border-accent-500 text-ink"
                    : "border-b-2 border-transparent text-ink-faint hover:text-ink-dim"
                }`}
              >
                <span className="inline-flex items-center gap-1.5">
                  {t}
                  {stale && (
                    <span
                      title="Render failed -- this view is from the prior successful render"
                      className="h-1.5 w-1.5 rounded-full bg-rose-400"
                      aria-label="stale"
                    />
                  )}
                </span>
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-3">
          {tab === "wiring" && design && (
            <div className="hidden @3xl:block"><WiringLegend /></div>
          )}
          <button
            onClick={copy}
            disabled={!content}
            title={`Copy the ${tab.toUpperCase()} to the clipboard`}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-ink-faint transition-colors enabled:hover:bg-surface-2 enabled:hover:text-ink disabled:opacity-40"
          >
            {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-4 font-mono text-[13px] leading-snug">
        {renderError && (
          <Notice tone="rose" title="Render failed" className="mb-3 text-sm">
            <div className="mt-1 whitespace-pre-wrap text-xs">{renderError}</div>
            {tabStale && (
              <div className="mt-2 border-t border-rose-500/30 pt-2 text-[11px] text-rose-200/80">
                The {tab.toUpperCase()} view below is from the last successful render
                — it does not reflect your current edits. Switch to the JSON tab to see
                the live design state, or fix the error above to refresh this view.
              </div>
            )}
          </Notice>
        )}

        {!design ? (
          <div className="flex h-full items-center justify-center text-center text-sm text-ink-ghost">
            Pick an example or board to start a design.
          </div>
        ) : tab === "wiring" ? (
          <>
            <div className="mb-3 @3xl:hidden"><WiringLegend /></div>
            <WiringView design={design} />
          </>
        ) : tab === "schematic" || tab === "pcb" ? (
          <ServerRenderView design={design} kind={tab} />
        ) : content ? (
          // Visual de-emphasis on stale content: lower opacity makes the
          // "this isn't current" state obvious without hiding the content
          // (it's still useful context for what the prior render produced).
          <pre
            className={`whitespace-pre text-ink transition-opacity ${
              tabStale ? "opacity-50" : ""
            }`}
          >
            {content}
          </pre>
        ) : (
          <Loading />
        )}
      </div>
    </section>
  );
}

interface DesignMeta {
  id: string;
  name: string;
  description: string;
  boardId: string;
  mcu: string;
  framework: string | null;
  componentCount: number;
  busCount: number;
  connectionCount: number;
}

function readMeta(d: Design): DesignMeta {
  const board = (d.board ?? {}) as Record<string, unknown>;
  const components = Array.isArray(d.components) ? d.components : [];
  const buses = Array.isArray(d.buses) ? d.buses : [];
  const connections = Array.isArray(d.connections) ? d.connections : [];
  return {
    id: String(d.id ?? ""),
    name: String(d.name ?? ""),
    description: String(d.description ?? ""),
    boardId: String(board.library_id ?? ""),
    mcu: String(board.mcu ?? ""),
    framework: board.framework ? String(board.framework) : null,
    componentCount: components.length,
    busCount: buses.length,
    connectionCount: connections.length,
  };
}
