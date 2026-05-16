import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api/client";
import type {
  BoardSummary,
  ComponentSummary,
  Design,
  ExampleSummary,
  PinAssignment,
  RenderResponse,
  SavedDesignSummary,
  SolverWarning,
} from "./types/api";
import { LeftSidebar } from "./components/LeftSidebar";
import { DesignPane } from "./components/DesignPane";
import { Inspector, type Selection } from "./components/Inspector";
import { UsbDetectDialog } from "./components/UsbDetectDialog";
import { AgentSidebar } from "./components/AgentSidebar";
import { SolveResultBanner } from "./components/SolveResultBanner";
import { NewDesignDialog } from "./components/NewDesignDialog";
import { PushToFleetDialog } from "./components/PushToFleetDialog";
import { CapabilityPickerDialog } from "./components/CapabilityPickerDialog";
import { EnclosureDialog } from "./components/EnclosureDialog";
import { SchematicDialog } from "./components/SchematicDialog";
import { useDebouncedValue } from "./lib/debounce";
import { useAdvancedMode } from "./lib/uiMode";
import {
  Bot,
  FilePlus,
  Save,
  Wand2,
  Usb,
  Plus,
  Cpu,
  Box,
  UploadCloud,
  RotateCcw,
  Download,
  ExternalLink
} from "lucide-react";
import {
  addComponent,
  isDirty,
  prepareBusesForLib,
  readBuses,
  setLockedPin,
  removeComponent,
  updateComponentParam,
  updateConnectionTarget,
  type ConnectionTarget,
  type LibraryComponentDetail,
} from "./lib/design";

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
  /** Strict mode: when true, the render endpoint refuses to produce
   *  YAML/ASCII while compatibility warnings of severity warn or error
   *  remain. Useful as a pre-deploy gate -- the design has to be clean
   *  before push-to-fleet. Default permissive so the user isn't blocked
   *  while editing. */
  const [strictMode, setStrictMode] = useState<boolean>(false);
  /** Advanced mode reveals the schematic / enclosure / push-to-fleet /
   *  agent surfaces. Default basic so the front door is the verified-tier
   *  flow (board + components + buses + YAML preview). Persists to
   *  localStorage. */
  const [advancedMode, setAdvancedMode] = useAdvancedMode();

  const [boardData, setBoardData] = useState<unknown | null>(null);

  const [selection, setSelection] = useState<Selection>({ kind: "design" });
  const [showUsbDialog, setShowUsbDialog] = useState(false);
  const [showAgent, setShowAgent] = useState(false);
  const [solveBanner, setSolveBanner] = useState<{
    assigned: PinAssignment[];
    unresolved: SolverWarning[];
    warnings: SolverWarning[];
  } | null>(null);
  const [solving, setSolving] = useState(false);

  const [savedDesigns, setSavedDesigns] = useState<SavedDesignSummary[] | null>(null);
  const [selectedSaved, setSelectedSaved] = useState<string | null>(null);
  const [showNewDialog, setShowNewDialog] = useState(false);
  const [showFleetDialog, setShowFleetDialog] = useState(false);
  const [showEnclosureDialog, setShowEnclosureDialog] = useState(false);
  const [showSchematicDialog, setShowSchematicDialog] = useState(false);
  const [showCapabilityDialog, setShowCapabilityDialog] = useState(false);
  const [savingState, setSavingState] = useState<"idle" | "saving" | "saved">("idle");

  const dirty = useMemo(() => isDirty(originalDesign, design), [originalDesign, design]);
  const debouncedDesign = useDebouncedValue(design, 250);

  // Bootstrap.
  useEffect(() => {
    (async () => {
      try {
        const [h, ex, bd, co, sv] = await Promise.all([
          api.health(),
          api.listExamples(),
          api.listBoards(),
          api.listComponents(),
          api.listSavedDesigns(),
        ]);
        setVersion(h.version);
        setExamples(ex);
        setBoards(bd);
        setComponents(co);
        setSavedDesigns(sv);
        if (ex.length > 0) setSelectedExample(ex[0].id);
      } catch (e) {
        const msg = e instanceof ApiError
          ? `${e.status}: ${e.message}`
          : e instanceof Error ? e.message : String(e);
        setBootError(msg);
      }
    })();
  }, []);

  async function refreshSavedDesigns() {
    try {
      setSavedDesigns(await api.listSavedDesigns());
    } catch {
      // non-fatal -- the sidebar will just show what it had before
    }
  }

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

  // Refs so the SSE handler can read the latest design/originalDesign
  // without re-creating the EventSource on every keystroke. Using state
  // in the handler's closure would freeze whatever was current at the
  // time the effect ran.
  const designRef = useRef<Design | null>(design);
  const originalDesignRef = useRef<Design | null>(originalDesign);
  useEffect(() => { designRef.current = design; }, [design]);
  useEffect(() => { originalDesignRef.current = originalDesign; }, [originalDesign]);

  // Mirror the browser's selectedSaved into the server's active-design
  // pointer so MCP tool calls default their `design_id` to whatever the
  // user is currently looking at. "Add a BME280 to this design" in chat
  // then resolves naturally against the visible design.
  useEffect(() => {
    void api.setActiveDesign(selectedSaved);
  }, [selectedSaved]);

  // Subscribe to design-changed events for the active saved design. Any
  // write from the MCP tool surface (or another tab, or the CLI) fires a
  // `saved` event we react to by re-fetching. If the user has unsaved
  // local edits we skip the refresh -- silently overwriting them would
  // be hostile. `deleted` always wins because the design is gone.
  useEffect(() => {
    if (!selectedSaved) return;
    if (typeof EventSource === "undefined") return;
    const id = selectedSaved;
    const url = `/api/designs/${encodeURIComponent(id)}/events`;
    const es = new EventSource(url);
    console.log("[wirestudio] SSE opening", url);
    es.addEventListener("open", () => console.log("[wirestudio] SSE open", url));
    es.addEventListener("error", (e) => console.warn("[wirestudio] SSE error", url, e));
    es.addEventListener("hello", (ev) =>
      console.log("[wirestudio] SSE hello", (ev as MessageEvent).data),
    );
    es.addEventListener("saved", (ev) => {
      const dirty = isDirty(originalDesignRef.current, designRef.current);
      console.log("[wirestudio] SSE saved", { dirty, data: (ev as MessageEvent).data });
      if (dirty) return;
      (async () => {
        try {
          const d = await api.getSavedDesign(id);
          setOriginalDesign(d);
          setDesign(d);
          void refreshSavedDesigns();
          console.log("[wirestudio] SSE saved -> design refreshed");
        } catch (err) {
          console.warn("[wirestudio] SSE saved -> refresh failed", err);
        }
      })();
    });
    es.addEventListener("deleted", (ev) => {
      console.log("[wirestudio] SSE deleted", (ev as MessageEvent).data);
      setSelectedSaved(null);
      setOriginalDesign(null);
      setDesign(null);
      void refreshSavedDesigns();
    });
    return () => {
      console.log("[wirestudio] SSE closing", url);
      es.close();
    };
  }, [selectedSaved]);

  // Cache the full library board for the design's `board.library_id`.
  // ConnectionForm needs rails + GPIO capabilities; refetching per inspector
  // selection would re-hit the API on every back-and-forth.
  const boardLibraryId = (design && (design.board as Record<string, unknown> | undefined)?.library_id) as
    | string | undefined;
  useEffect(() => {
    if (!boardLibraryId) { setBoardData(null); return; }
    let cancelled = false;
    api.getBoard(boardLibraryId).then((b) => { if (!cancelled) setBoardData(b); }).catch(() => {});
    return () => { cancelled = true; };
  }, [boardLibraryId]);

  // Debounced render whenever the design changes.
  useEffect(() => {
    if (!debouncedDesign) return;
    let cancelled = false;
    setRendering(true);
    (async () => {
      try {
        const r = await api.render(debouncedDesign, { strict: strictMode });
        if (cancelled) return;
        setRender(r);
        setRenderError(null);
      } catch (e) {
        if (cancelled) return;
        let msg: string;
        if (e instanceof ApiError) {
          // Strict-mode rejection: detail = { error, message, warnings: [...] }.
          // Surface the message + count instead of the raw JSON blob.
          const body = e.body as
            | { detail?: { error?: string; message?: string; warnings?: unknown[] } }
            | undefined;
          const detail = body?.detail;
          if (detail?.error === "strict_mode_blocked" && detail.message) {
            msg = `${e.status}: ${detail.message}`;
          } else {
            msg = `${e.status}: ${e.message}`;
          }
        } else {
          msg = e instanceof Error ? e.message : String(e);
        }
        setRenderError(msg);
      } finally {
        if (!cancelled) setRendering(false);
      }
    })();
    return () => { cancelled = true; };
  }, [debouncedDesign, strictMode]);

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

  function handleConnectionChange(connectionIndex: number, target: ConnectionTarget) {
    setDesign((d) => (d ? updateConnectionTarget(d, connectionIndex, target) : d));
  }

  function handleLockedPinChange(componentId: string, pinRole: string, pin: string | null) {
    setDesign((d) => (d ? setLockedPin(d, componentId, pinRole, pin) : d));
  }

  function handleDesignChange(updater: (d: Design) => Design) {
    setDesign((d) => (d ? updater(d) : d));
  }

  async function handleAddComponent(libraryId: string) {
    let lib: LibraryComponentDetail;
    try {
      lib = (await api.getComponent(libraryId)) as LibraryComponentDetail;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setRenderError(`Could not fetch library component '${libraryId}': ${msg}`);
      return;
    }
    setDesign((d) => {
      if (!d) return d;
      const board = boardData as {
        rails?: Array<{ name: string; voltage: number }>;
        default_buses?: Record<string, Record<string, string>>;
      } | null;
      const ctx = {
        rails: board?.rails ?? [],
        default_buses: board?.default_buses ?? {},
      };
      // 1. Auto-add any bus types this component needs but the design lacks.
      // 2. Then add the component (its connections will pick up the buses).
      const withBuses = prepareBusesForLib(d, lib, ctx);
      return addComponent(withBuses, lib, { board: ctx, buses: readBuses(withBuses) });
    });
  }

  function handleRemoveComponent(instanceId: string) {
    setDesign((d) => (d ? removeComponent(d, instanceId) : d));
    if (selection.kind === "component_instance" && selection.id === instanceId) {
      setSelection({ kind: "design" });
    }
  }

  function handleAdoptDetectedDesign(d: Design) {
    setOriginalDesign(d);
    setDesign(d);
    setSelectedExample(null);  // detached from the examples sidebar
    setSelectedSaved(null);
    setSelection({ kind: "design" });
    setShowUsbDialog(false);
  }

  function handleAdoptNewDesign(d: Design) {
    setOriginalDesign(d);
    setDesign(d);
    setSelectedExample(null);
    setSelectedSaved(null);
    setSelection({ kind: "design" });
    setShowNewDialog(false);
  }

  async function handleSelectSaved(id: string) {
    try {
      const d = await api.getSavedDesign(id);
      setOriginalDesign(d);
      setDesign(d);
      setSelectedExample(null);
      setSelectedSaved(id);
      setSelection({ kind: "design" });
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status}: ${e.message}` : String(e);
      setRenderError(msg);
    }
  }

  async function handleDeleteSaved(id: string) {
    try {
      await api.deleteSavedDesign(id);
      if (selectedSaved === id) setSelectedSaved(null);
      await refreshSavedDesigns();
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status}: ${e.message}` : String(e);
      setRenderError(msg);
    }
  }

  async function handleSave() {
    if (!design || savingState === "saving") return;
    setSavingState("saving");
    try {
      const r = await api.saveDesign(design);
      setSelectedSaved(r.id);
      setOriginalDesign(design);  // saved state is the new "reset target"
      await refreshSavedDesigns();
      setSavingState("saved");
      window.setTimeout(() => setSavingState("idle"), 1500);
    } catch (e) {
      const msg = e instanceof ApiError
        ? `${e.status}: ${e.message}`
        : e instanceof Error ? e.message : String(e);
      setRenderError(msg);
      setSavingState("idle");
    }
  }

  function handleAgentDesignReplaced(next: Design) {
    // Agent edits flow into the working design; originalDesign stays as the
    // user's "reset target" -- they can still revert agent changes via the
    // header's Reset button, just as with manual edits.
    setDesign(next);
  }

  async function handleSolvePins() {
    if (!design || solving) return;
    setSolving(true);
    try {
      const r = await api.solvePins(design);
      setDesign(r.design);
      setSolveBanner({
        assigned: r.assigned,
        unresolved: r.unresolved,
        warnings: r.warnings,
      });
    } catch (e) {
      const msg = e instanceof ApiError
        ? `${e.status}: ${e.message}`
        : e instanceof Error ? e.message : String(e);
      setRenderError(msg);
    } finally {
      setSolving(false);
    }
  }

  if (bootError) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-sm">
        <div className="max-w-lg rounded border border-red-500/40 bg-red-500/10 p-4">
          <div className="mb-2 font-semibold text-red-300">Could not reach the studio API.</div>
          <div className="text-zinc-300">{bootError}</div>
          <div className="mt-3 text-xs text-zinc-400">
            Start it with <code className="rounded bg-zinc-800 px-1.5 py-0.5">python -m wirestudio.api</code> and refresh.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="grid h-full grid-rows-[auto_auto_1fr] bg-zinc-950 text-zinc-200">
      <header className="flex h-14 items-center justify-between border-b border-zinc-800 bg-zinc-950 px-4">
        {/* Left: Branding & Status */}
=======
        <div className="flex items-center gap-4">
          <div className="flex items-baseline gap-2">
            <h1 className="text-lg font-semibold tracking-tight text-zinc-100">wirestudio</h1>
            <span className="text-xs font-medium text-zinc-500">{version ? `v${version}` : "..."}</span>
          </div>

          <div className="flex items-center gap-2 border-l border-zinc-800 pl-4">
            {rendering && (
              <span className="flex items-center gap-1.5 text-xs text-blue-400">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75"></span>
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-500"></span>
                </span>
                rendering
              </span>
            )}
            {dirty && !rendering && (
              <span className="rounded-md bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-400 ring-1 ring-amber-500/30">
                Unsaved changes
              </span>
            )}
          </div>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-3">
          {/* Group 1: Core Design Actions */}
=======
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1 rounded-md bg-zinc-900/50 p-1 ring-1 ring-inset ring-zinc-800">
            <button
              onClick={() => setShowNewDialog(true)}
              className="flex items-center gap-1.5 rounded p-1.5 text-xs font-medium text-zinc-300 transition-colors hover:bg-zinc-800 hover:text-zinc-100"
              title="Create a fresh design from a board"
            >
              <FilePlus className="h-4 w-4" />
              <span className="hidden sm:inline">New</span>
            </button>

            <button
              disabled={!design || savingState === "saving"}
              onClick={handleSave}
              className={`flex items-center gap-1.5 rounded p-1.5 text-xs font-medium transition-colors disabled:opacity-40 ${
                savingState === "saved"
                  ? "bg-emerald-500/20 text-emerald-300"
                  : "text-zinc-300 enabled:hover:bg-zinc-800 enabled:hover:text-zinc-100"
              }`}
              title="Persist the current design to designs/<id>.json on the server"
            >
              <Save className="h-4 w-4" />
              <span className="hidden sm:inline">
                {savingState === "saving" ? "Saving..." : savingState === "saved" ? "Saved" : "Save"}
              </span>
            </button>

            <div className="mx-1 h-4 w-px bg-zinc-700"></div>

            <button
              disabled={!dirty}
              onClick={handleReset}
              className="flex items-center gap-1.5 rounded p-1.5 text-xs font-medium text-zinc-300 transition-colors enabled:hover:bg-zinc-800 enabled:hover:text-zinc-100 disabled:opacity-40"
              title="Reset to last saved state"
            >
              <RotateCcw className="h-4 w-4" />
              <span className="hidden lg:inline">Reset</span>
            </button>

            <button
              disabled={!design}
              onClick={handleDownload}
              className="flex items-center gap-1.5 rounded p-1.5 text-xs font-medium text-zinc-300 transition-colors enabled:hover:bg-zinc-800 enabled:hover:text-zinc-100 disabled:opacity-40"
              title="Download JSON"
=======
              title="Download design as JSON"
              aria-label="Download design as JSON"
            >
              <Download className="h-4 w-4" />
            </button>
          </div>

          {/* Group 2: Builder Actions */}
=======
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowUsbDialog(true)}
              className="flex items-center gap-1.5 rounded-md bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-200 transition-colors hover:bg-zinc-700"
              title="Detect a connected ESP via WebSerial"
            >
              <Usb className="h-4 w-4 text-zinc-400" />
              Connect Device
            </button>

            <button
              disabled={!design}
              onClick={() => setShowCapabilityDialog(true)}
              className="flex items-center gap-1.5 rounded-md bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-200 transition-colors enabled:hover:bg-zinc-700 disabled:opacity-40"
              title="Pick a capability and add a matching component"
            >
              <Plus className="h-4 w-4 text-zinc-400" />
              Add Component
=======
              Add by Function
            </button>

            <button
              disabled={!design || solving}
              onClick={handleSolvePins}
              className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors enabled:hover:bg-blue-500 disabled:opacity-40"
              title="Auto-assign every unbound connection"
            >
              <Wand2 className="h-4 w-4" />
              {solving ? "Solving..." : "Solve Pins"}
            </button>
          </div>

          {/* Group 3: Advanced & Export Actions */}
=======
          {advancedMode && (
            <div className="flex items-center gap-1 border-l border-zinc-800 pl-3">
              <button
                disabled={!design}
                onClick={() => setShowSchematicDialog(true)}
                className="flex items-center gap-1.5 rounded p-1.5 text-xs font-medium text-zinc-400 transition-colors enabled:hover:bg-zinc-800 enabled:hover:text-zinc-200 disabled:opacity-40"
                title="Schematic (KiCad)"
=======
                title="Download a SKiDL Python script that produces a .kicad_sch when run locally"
                aria-label="Schematic (KiCad export)"
              >
                <Cpu className="h-4 w-4" />
              </button>
              <button
                disabled={!design}
                onClick={() => setShowEnclosureDialog(true)}
                className="flex items-center gap-1.5 rounded p-1.5 text-xs font-medium text-zinc-400 transition-colors enabled:hover:bg-zinc-800 enabled:hover:text-zinc-200 disabled:opacity-40"
                title="Enclosure Model"
=======
                title="Generate a parametric .scad enclosure shell or search community models"
                aria-label="Enclosure"
              >
                <Box className="h-4 w-4" />
              </button>
              <button
                disabled={!design}
                onClick={() => setShowFleetDialog(true)}
                className="flex items-center gap-1.5 rounded p-1.5 text-xs font-medium text-zinc-400 transition-colors enabled:hover:bg-zinc-800 enabled:hover:text-zinc-200 disabled:opacity-40"
                title="Push to Fleet"
=======
                title="Push the rendered YAML to the fleet-for-esphome add-on"
                aria-label="Push to fleet"
              >
                <UploadCloud className="h-4 w-4" />
              </button>

              <div className="mx-1 h-4 w-px bg-zinc-800"></div>

              <button
                onClick={() => setShowAgent(true)}
                className="flex items-center gap-1.5 rounded p-1.5 text-xs font-medium text-blue-400 transition-colors hover:bg-blue-500/10 hover:text-blue-300"
                title="Open the design agent"
              >
                <Bot className="h-4 w-4" />
                <span className="hidden lg:inline">Agent</span>
              </button>
            </div>
          )}

          {/* Group 4: Settings & Links */}
=======
          <div className="flex items-center gap-2 border-l border-zinc-800 pl-3">
            <div className="flex flex-col gap-1">
              <label
                className="flex cursor-pointer items-center gap-1.5 text-[10px] font-medium text-zinc-400 transition-colors hover:text-zinc-200"
                title="Strict mode: render fails when compatibility warnings of severity warn or error remain"
              >
                <input
                  type="checkbox"
                  checked={strictMode}
                  onChange={(e) => setStrictMode(e.target.checked)}
                  className="h-3 w-3 rounded-sm border-zinc-700 bg-zinc-900 accent-blue-500"
                />
                STRICT
              </label>
              <label
                className="flex cursor-pointer items-center gap-1.5 text-[10px] font-medium text-zinc-400 transition-colors hover:text-zinc-200"
                title="Advanced mode reveals Agent, Schematic, Enclosure, and Fleet options"
              >
                <input
                  type="checkbox"
                  checked={advancedMode}
                  onChange={(e) => setAdvancedMode(e.target.checked)}
                  className="h-3 w-3 rounded-sm border-zinc-700 bg-zinc-900 accent-violet-500"
                />
                ADVANCED
              </label>
            </div>

            <a
              href="/api/docs" target="_blank" rel="noreferrer"
              className="ml-1 flex items-center gap-1 rounded p-1.5 text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-zinc-300"
              title="OpenAPI Documentation"
=======
              title="OpenAPI documentation"
              aria-label="OpenAPI documentation"
            >
              <ExternalLink className="h-4 w-4" />
            </a>
          </div>
        </div>
      </header>
      {solveBanner && (
        <SolveResultBanner
          assigned={solveBanner.assigned}
          unresolved={solveBanner.unresolved}
          warnings={solveBanner.warnings}
          onDismiss={() => setSolveBanner(null)}
        />
      )}
      <main className="grid min-h-0 grid-cols-[18rem_1fr_24rem]">
        <LeftSidebar
          examples={examples}
          saved={savedDesigns}
          boards={boards}
          components={components}
          selectedExample={selectedExample}
          selectedSaved={selectedSaved}
          onSelectExample={(id) => { setSelectedSaved(null); setSelectedExample(id); }}
          onSelectSaved={handleSelectSaved}
          onDeleteSaved={handleDeleteSaved}
          onSelectBoard={(id) => setSelection({ kind: "board", id })}
          onSelectComponent={(id) => setSelection({ kind: "component", id })}
        />
        <DesignPane design={design} render={render} renderError={renderError} />
        <Inspector
          selection={selection}
          design={design}
          boardData={boardData}
          libraryBoards={boards}
          libraryComponents={components}
          compatibilityWarnings={render?.compatibility_warnings ?? []}
          onSelect={setSelection}
          onParamChange={handleParamChange}
          onConnectionChange={handleConnectionChange}
          onLockedPinChange={handleLockedPinChange}
          onDesignChange={handleDesignChange}
          onAddComponent={handleAddComponent}
          onRemoveComponent={handleRemoveComponent}
        />
      </main>
      {showUsbDialog && (
        <UsbDetectDialog
          boards={boards}
          onCancel={() => setShowUsbDialog(false)}
          onAdopt={handleAdoptDetectedDesign}
        />
      )}
      {showNewDialog && (
        <NewDesignDialog
          boards={boards}
          onCancel={() => setShowNewDialog(false)}
          onAdopt={handleAdoptNewDesign}
        />
      )}
      {showFleetDialog && design && (
        <PushToFleetDialog
          design={design}
          strict={strictMode}
          onClose={() => setShowFleetDialog(false)}
        />
      )}
      {showSchematicDialog && design && (
        <SchematicDialog
          design={design}
          onClose={() => setShowSchematicDialog(false)}
        />
      )}
      {showEnclosureDialog && design && (
        <EnclosureDialog
          design={design}
          boardLibraryId={String((design.board as Record<string, unknown> | undefined)?.library_id ?? "")}
          boardName={String(
            (boards ?? []).find(
              (b) => b.id === String((design.board as Record<string, unknown> | undefined)?.library_id ?? ""),
            )?.name ?? (design.board as Record<string, unknown> | undefined)?.library_id ?? "Board",
          )}
          onClose={() => setShowEnclosureDialog(false)}
        />
      )}
      {showCapabilityDialog && (
        <CapabilityPickerDialog
          designReady={!!design}
          designBusTypes={Array.from(new Set(readBuses(design).map((b) => b.type)))}
          onAdd={async (libraryId) => {
            await handleAddComponent(libraryId);
          }}
          onClose={() => setShowCapabilityDialog(false)}
        />
      )}
      <AgentSidebar
        open={showAgent}
        design={design}
        onClose={() => setShowAgent(false)}
        onDesignReplaced={handleAgentDesignReplaced}
      />
    </div>
  );
}
