import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "./api/client";
import type { BoardSummary, ComponentSummary, Design, ExampleSummary, RenderResponse } from "./types/api";
import { LeftSidebar } from "./components/LeftSidebar";
import { DesignPane } from "./components/DesignPane";
import { Inspector, type Selection } from "./components/Inspector";
import { useDebouncedValue } from "./lib/debounce";
import { isDirty, updateComponentParam } from "./lib/design";

export default function App() {
  const [examples, setExamples] = useState<ExampleSummary[] | null>(null);
  const [boards, setBoards] = useState<BoardSummary[] | null>(null);
  const [components, setComponents] = useState<ComponentSummary[] | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);
  const [version, setVersion] = useState<string | null>(null);

  const [selectedExample, setSelectedExample] = useState<string | null>(null);
  const [originalDesign, setOriginalDesign] = useState<Design | null>(null);
  const [design, setDesign] = useState<Design | null>(null);

  const [render, setRender] = useState<RenderResponse | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [rendering, setRendering] = useState(false);

  const [selection, setSelection] = useState<Selection>({ kind: "design" });

  const dirty = useMemo(() => isDirty(originalDesign, design), [originalDesign, design]);
  const debouncedDesign = useDebouncedValue(design, 250);

  // Bootstrap.
  useEffect(() => {
    (async () => {
      try {
        const [h, ex, bd, co] = await Promise.all([
          api.health(),
          api.listExamples(),
          api.listBoards(),
          api.listComponents(),
        ]);
        setVersion(h.version);
        setExamples(ex);
        setBoards(bd);
        setComponents(co);
        if (ex.length > 0) setSelectedExample(ex[0].id);
      } catch (e) {
        const msg = e instanceof ApiError
          ? `${e.status}: ${e.message}`
          : e instanceof Error ? e.message : String(e);
        setBootError(msg);
      }
    })();
  }, []);

  // Load the selected example fresh.
  useEffect(() => {
    if (!selectedExample) return;
    let cancelled = false;
    (async () => {
      setRenderError(null);
      try {
        const d = await api.getExample(selectedExample);
        if (cancelled) return;
        setOriginalDesign(d);
        setDesign(d);
        setSelection({ kind: "design" });
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof ApiError
          ? `${e.status}: ${e.message}`
          : e instanceof Error ? e.message : String(e);
        setRenderError(msg);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedExample]);

  // Debounced render whenever the design changes.
  useEffect(() => {
    if (!debouncedDesign) return;
    let cancelled = false;
    setRendering(true);
    (async () => {
      try {
        const r = await api.render(debouncedDesign);
        if (cancelled) return;
        setRender(r);
        setRenderError(null);
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof ApiError
          ? `${e.status}: ${e.message}`
          : e instanceof Error ? e.message : String(e);
        setRenderError(msg);
      } finally {
        if (!cancelled) setRendering(false);
      }
    })();
    return () => { cancelled = true; };
  }, [debouncedDesign]);

  function handleReset() {
    if (!originalDesign) return;
    setDesign(originalDesign);
    setSelection({ kind: "design" });
  }

  function handleDownload() {
    if (!design) return;
    const id = String(design.id ?? "design");
    const blob = new Blob([JSON.stringify(design, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${id}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function handleParamChange(componentInstanceId: string, paramKey: string, value: unknown) {
    setDesign((d) => (d ? updateComponentParam(d, componentInstanceId, paramKey, value) : d));
  }

  if (bootError) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-sm">
        <div className="max-w-lg rounded border border-red-500/40 bg-red-500/10 p-4">
          <div className="mb-2 font-semibold text-red-300">Could not reach the studio API.</div>
          <div className="text-zinc-300">{bootError}</div>
          <div className="mt-3 text-xs text-zinc-400">
            Start it with <code className="rounded bg-zinc-800 px-1.5 py-0.5">python -m studio.api</code> and refresh.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="grid h-full grid-rows-[auto_1fr] bg-zinc-950 text-zinc-200">
      <header className="flex items-center justify-between border-b border-zinc-800 px-4 py-2">
        <div className="flex items-baseline gap-3">
          <h1 className="text-base font-semibold tracking-tight">esphome-studio</h1>
          <span className="text-xs text-zinc-500">{version ? `API v${version}` : "connecting..."}</span>
          {rendering && <span className="text-xs text-blue-300">rendering...</span>}
          {dirty && !rendering && (
            <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-xs text-amber-200 ring-1 ring-amber-500/40">
              modified
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            disabled={!dirty}
            onClick={handleReset}
            className="rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-300 enabled:hover:bg-zinc-900 disabled:opacity-40"
          >
            Reset
          </button>
          <button
            disabled={!design}
            onClick={handleDownload}
            className="rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-300 enabled:hover:bg-zinc-900 disabled:opacity-40"
          >
            Download JSON
          </button>
          <a
            href="/api/docs" target="_blank" rel="noreferrer"
            className="text-xs text-zinc-400 hover:text-zinc-200"
          >
            OpenAPI ↗
          </a>
        </div>
      </header>
      <main className="grid min-h-0 grid-cols-[18rem_1fr_24rem]">
        <LeftSidebar
          examples={examples}
          boards={boards}
          components={components}
          selectedExample={selectedExample}
          onSelectExample={setSelectedExample}
          onSelectBoard={(id) => setSelection({ kind: "board", id })}
          onSelectComponent={(id) => setSelection({ kind: "component", id })}
        />
        <DesignPane design={design} render={render} renderError={renderError} />
        <Inspector
          selection={selection}
          design={design}
          onSelect={setSelection}
          onParamChange={handleParamChange}
        />
      </main>
    </div>
  );
}
