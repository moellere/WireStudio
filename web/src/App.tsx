import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, UNAUTHORIZED_EVENT } from "./api/client";
import { ApiTokenDialog } from "./components/ApiTokenDialog";
import type {
  BoardSummary,
  ComponentSummary,
  Design,
  CommunityStatus,
  ExampleSummary,
  ModuleSummary,
  PinAssignment,
  RenderResponse,
  SavedDesignSummary,
  SolverWarning,
} from "./types/api";
import { LeftSidebar, type CommunityList } from "./components/LeftSidebar";
import { DesignPane } from "./components/DesignPane";
import { Inspector, type Selection } from "./components/Inspector";
import { UsbDetectDialog } from "./components/UsbDetectDialog";
import { AgentSidebar } from "./components/AgentSidebar";
import { SolveResultBanner } from "./components/SolveResultBanner";
import { NewDesignDialog } from "./components/NewDesignDialog";
import { FeedbackLink } from "./components/FeedbackLink";
import { PushToFleetDialog } from "./components/PushToFleetDialog";
import { CapabilityPickerDialog } from "./components/CapabilityPickerDialog";
import { EnclosureDialog } from "./components/EnclosureDialog";
import { SchematicDialog } from "./components/SchematicDialog";
import { FlashDialog } from "./components/FlashDialog";
import { LorawanProvisionEsphomeDialog } from "./components/LorawanProvisionEsphomeDialog";
import { InventoryDialog } from "./components/InventoryDialog";
import { LibraryEditorDialog, NEW_BOARD_TEMPLATE, NEW_COMPONENT_TEMPLATE, type LibraryKind } from "./components/LibraryEditorDialog";
import { SettingsDialog } from "./components/SettingsDialog";
import { ShareDialog } from "./components/ShareDialog";
import { useDebouncedValue } from "./lib/debounce";
import { useAdvancedMode } from "./lib/uiMode";
import { useTheme } from "./lib/theme";
import {
  Bot,
  FilePlus,
  Save,
  Share2,
  Wand2,
  Usb,
  Plus,
  Cpu,
  Box,
  UploadCloud,
  RotateCcw,
  Download,
  ExternalLink,
  Settings,
  Radio,
  Boxes,
  KeyRound,
  Sun,
  Moon,
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
  const [modules, setModules] = useState<ModuleSummary[] | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);
  const [bootNonce, setBootNonce] = useState(0);
  const [showTokenDialog, setShowTokenDialog] = useState(false);
  const [version, setVersion] = useState<string | null>(null);

  const [selectedExample, setSelectedExample] = useState<string | null>(null);
  const [communityStatus, setCommunityStatus] = useState<CommunityStatus | null>(null);
  const [community, setCommunity] = useState<CommunityList | null>(null);
  const [selectedCommunity, setSelectedCommunity] = useState<string | null>(null);
  const [showShareDialog, setShowShareDialog] = useState(false);
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
  // Strict mode lives on the design (design.strict) so it persists and every
  // surface honors the same value; the checkbox writes it via setDesign.
  const strictMode = design?.strict === true;
  /** Advanced mode reveals the schematic / enclosure / push-to-fleet /
   *  agent surfaces. Default basic so the front door is the verified-tier
   *  flow (board + components + buses + YAML preview). Persists to
   *  localStorage. */
  const [advancedMode, setAdvancedMode] = useAdvancedMode();
  const [theme, setTheme] = useTheme();

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
  const [showFlashDialog, setShowFlashDialog] = useState(false);
  const [showProvisionEsphomeDialog, setShowProvisionEsphomeDialog] = useState(false);
  const [showInventoryDialog, setShowInventoryDialog] = useState(false);
  const [libraryEditor, setLibraryEditor] = useState<{ kind: LibraryKind; title: string; yaml: string; overwrite: boolean } | null>(null);
  const [showSettingsDialog, setShowSettingsDialog] = useState(false);
  const [savingState, setSavingState] = useState<"idle" | "saving" | "saved">("idle");

  const dirty = useMemo(() => isDirty(originalDesign, design), [originalDesign, design]);
  const debouncedDesign = useDebouncedValue(design, 250);
  const designBusTypes = useMemo(() => {
    if (!design) return [];
    const types = new Set<string>();
    for (const b of readBuses(design)) {
      types.add(b.type);
    }
    return Array.from(types);
  }, [design]);

  // A 401 anywhere means the studio wants its API token; ask once and
  // retry the boot with it.
  useEffect(() => {
    const onUnauthorized = () => setShowTokenDialog(true);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  // Bootstrap.
  useEffect(() => {
    (async () => {
      try {
        const [h, ex, bd, co, md, sv] = await Promise.all([
          api.health(),
          api.listExamples(),
          api.listBoards(),
          api.listComponents(),
          api.listModules(),
          api.listSavedDesigns(),
        ]);
        setVersion(h.version);
        setExamples(ex);
        setBoards(bd);
        setComponents(co);
        setModules(md);
        setSavedDesigns(sv);
        if (ex.length > 0) setSelectedExample(ex[0].id);
        void loadCommunity();
      } catch (e) {
        const msg = e instanceof ApiError
          ? `${e.status}: ${e.message}`
          : e instanceof Error ? e.message : String(e);
        setBootError(msg);
      }
    })();
  }, [bootNonce]);

  const tokenDialog = showTokenDialog && (
    <ApiTokenDialog
      onSaved={() => { setShowTokenDialog(false); setBootError(null); setBootNonce((n) => n + 1); }}
      onClose={() => setShowTokenDialog(false)}
    />
  );

  async function refreshComponents() {
    try {
      setComponents(await api.listComponents());
    } catch {
      /* the list keeps its last value */
    }
  }

  async function refreshBoards() {
    try {
      setBoards(await api.listBoards());
    } catch {
      /* the list keeps its last value */
    }
  }

  async function handleEditLibrary(kind: LibraryKind, id: string, source: "bundled" | "user") {
    try {
      const yaml = kind === "board" ? await api.getBoardYaml(id) : await api.getComponentYaml(id);
      if (source === "user") {
        setLibraryEditor({ kind, title: `Edit ${id}`, yaml, overwrite: true });
      } else {
        setLibraryEditor({
          kind,
          title: `New ${kind} from ${id}`,
          yaml: yaml.replace(/^id: .*$/m, `id: ${id}${kind === "board" ? "-copy" : "_copy"}`),
          overwrite: false,
        });
      }
    } catch (e) {
      setBootError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleDeleteBoard(id: string) {
    if (!window.confirm(`Remove ${id} from the user library? Designs on it stop rendering.`)) return;
    try {
      await api.deleteBoard(id);
      await refreshBoards();
      setSelection((sel) => (sel.kind === "board" && sel.id === id ? { kind: "design" } : sel));
    } catch (e) {
      setBootError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleDeleteComponent(id: string) {
    if (!window.confirm(`Remove ${id} from the user library? Designs that use it stop rendering.`)) return;
    try {
      await api.deleteComponent(id);
      await refreshComponents();
      setSelection((sel) => (sel.kind === "component" && sel.id === id ? { kind: "design" } : sel));
    } catch (e) {
      setBootError(e instanceof Error ? e.message : String(e));
    }
  }

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
        const r = await api.render(debouncedDesign);
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

  async function handleInsertModule(moduleId: string) {
    if (!design) {
      setRenderError("Open or create a design before inserting a module.");
      return;
    }
    try {
      const updated = await api.insertModule(design, moduleId);
      setDesign(updated);
      setSelection({ kind: "design" });
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status}: ${e.message}` : String(e);
      setRenderError(`Could not insert module '${moduleId}': ${msg}`);
    }
  }

  function handleRemoveComponent(instanceId: string) {
    setDesign((d) => (d ? removeComponent(d, instanceId) : d));
    if (selection.kind === "component_instance" && selection.id === instanceId) {
      setSelection({ kind: "design" });
    }
  }

  // The catalogue is optional: off, unreachable or slow, the rest of the
  // studio carries on and the gallery tab says why.
  async function loadCommunity() {
    let status: CommunityStatus;
    try {
      status = await api.communityStatus();
    } catch {
      return;
    }
    setCommunityStatus(status);
    if (!status.enabled) return;
    setCommunity({ items: null, error: null });
    try {
      const { designs } = await api.communityDesigns();
      setCommunity({ items: designs, error: null });
    } catch (e) {
      setCommunity({ items: null, error: e instanceof Error ? e.message : String(e) });
    }
  }

  async function handleSelectCommunity(slug: string) {
    try {
      const { design: d, installed_components } = await api.communityImport(slug);
      if (installed_components.length > 0) setComponents(await api.listComponents());
      setOriginalDesign(d);
      setDesign(d);
      setSelectedExample(null);
      setSelectedSaved(null);
      setSelectedCommunity(slug);
      setSelection({ kind: "design" });
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status}: ${e.message}` : String(e);
      setRenderError(msg);
    }
  }

  function handleAdoptDetectedDesign(d: Design) {
    setOriginalDesign(d);
    setDesign(d);
    setSelectedExample(null);  // detached from the examples sidebar
    setSelectedSaved(null);
    setSelectedCommunity(null);
    setSelection({ kind: "design" });
    setShowUsbDialog(false);
  }

  function handleAdoptNewDesign(d: Design) {
    setOriginalDesign(d);
    setDesign(d);
    setSelectedExample(null);
    setSelectedSaved(null);
    setSelectedCommunity(null);
    setSelection({ kind: "design" });
    setShowNewDialog(false);
  }

  async function handleSelectSaved(id: string) {
    try {
      const d = await api.getSavedDesign(id);
      setOriginalDesign(d);
      setDesign(d);
      setSelectedExample(null);
      setSelectedCommunity(null);
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
    const unauthorized = bootError.startsWith("401:");
    return (
      <div className="flex h-full items-center justify-center p-6 text-sm">
        <div className="max-w-lg rounded-md border border-rose-500/40 bg-rose-500/10 p-4">
          <div className="mb-2 font-semibold text-rose-300">
            {unauthorized ? "The studio API wants its token." : "Could not reach the studio API."}
          </div>
          <div className="text-ink-dim">{bootError}</div>
          <div className="mt-3 text-xs text-ink-faint">
            {unauthorized ? (
              <button className="underline" onClick={() => setShowTokenDialog(true)}>Enter the API token</button>
            ) : (
              <>Start it with <code className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono">python -m wirestudio.api</code> and refresh.</>
            )}
          </div>
        </div>
        {tokenDialog}
      </div>
    );
  }

  return (
    <div className="grid h-full grid-rows-[auto_auto_1fr] bg-surface-0 text-ink">
      <header className="flex h-14 items-center justify-between border-b border-line bg-surface-0 px-4">
        <div className="flex items-center gap-4">
          <div className="flex items-baseline gap-2">
            <h1 className="text-lg font-semibold tracking-tight text-ink">
              wire<span className="text-accent-400">studio</span>
            </h1>
            <span className="font-mono text-xs font-medium text-ink-faint">{version ? `v${version}` : "..."}</span>
          </div>

          <div className="flex items-center gap-2 border-l border-line pl-4">
            {rendering && (
              <span className="flex items-center gap-1.5 text-xs text-accent-300">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-400 opacity-75"></span>
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-accent-500"></span>
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

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1 rounded-lg bg-surface-1 p-1 ring-1 ring-inset ring-line">
            <button
              onClick={() => setShowNewDialog(true)}
              className="flex items-center gap-1.5 rounded-md p-1.5 text-xs font-medium text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink"
              title="Create a fresh design from a board"
            >
              <FilePlus className="h-4 w-4" />
              <span className="hidden sm:inline">New</span>
            </button>

            <button
              disabled={!design || savingState === "saving"}
              onClick={handleSave}
              className={`flex items-center gap-1.5 rounded-md p-1.5 text-xs font-medium transition-colors disabled:opacity-40 ${
                savingState === "saved"
                  ? "bg-emerald-500/20 text-emerald-300"
                  : "text-ink-dim enabled:hover:bg-surface-2 enabled:hover:text-ink"
              }`}
              title="Persist the current design to designs/<id>.json on the server"
            >
              <Save className="h-4 w-4" />
              <span className="hidden sm:inline">
                {savingState === "saving" ? "Saving..." : savingState === "saved" ? "Saved" : "Save"}
              </span>
            </button>

            {communityStatus?.enabled && (
              <button
                disabled={!design}
                onClick={() => setShowShareDialog(true)}
                className="flex items-center gap-1.5 rounded-md p-1.5 text-xs font-medium text-ink-dim transition-colors enabled:hover:bg-surface-2 enabled:hover:text-ink disabled:opacity-40"
                title="Share this design to the community catalogue"
              >
                <Share2 className="h-4 w-4" />
                <span className="hidden sm:inline">Share</span>
              </button>
            )}

            <div className="mx-1 h-4 w-px bg-line-strong"></div>

            <button
              disabled={!dirty}
              onClick={handleReset}
              className="flex items-center gap-1.5 rounded-md p-1.5 text-xs font-medium text-ink-dim transition-colors enabled:hover:bg-surface-2 enabled:hover:text-ink disabled:opacity-40"
              title="Reset to last saved state"
            >
              <RotateCcw className="h-4 w-4" />
              <span className="hidden lg:inline">Reset</span>
            </button>

            <button
              disabled={!design}
              onClick={handleDownload}
              className="flex items-center gap-1.5 rounded-md p-1.5 text-xs font-medium text-ink-dim transition-colors enabled:hover:bg-surface-2 enabled:hover:text-ink disabled:opacity-40"
              title="Download design as JSON"
              aria-label="Download design as JSON"
            >
              <Download className="h-4 w-4" />
            </button>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowUsbDialog(true)}
              className="flex items-center gap-1.5 rounded-md bg-surface-2 px-3 py-1.5 text-xs font-medium text-ink ring-1 ring-inset ring-line transition-colors hover:bg-surface-3 hover:ring-line-strong"
              title="Detect a connected ESP via WebSerial"
            >
              <Usb className="h-4 w-4 text-ink-faint" />
              Connect Device
            </button>

            <button
              disabled={!design}
              onClick={() => setShowCapabilityDialog(true)}
              className="flex items-center gap-1.5 rounded-md bg-surface-2 px-3 py-1.5 text-xs font-medium text-ink ring-1 ring-inset ring-line transition-colors enabled:hover:bg-surface-3 enabled:hover:ring-line-strong disabled:opacity-40"
              title="Pick a capability and add a matching component"
            >
              <Plus className="h-4 w-4 text-ink-faint" />
              Add by Function
            </button>

            <button
              onClick={() => setShowInventoryDialog(true)}
              className="flex items-center gap-1.5 rounded-md bg-surface-2 px-3 py-1.5 text-xs font-medium text-ink ring-1 ring-inset ring-line transition-colors hover:bg-surface-3 hover:ring-line-strong"
              title="View and edit your component inventory; check the open design against what's on hand"
            >
              <Boxes className="h-4 w-4 text-ink-faint" />
              Inventory
            </button>

            <button
              disabled={!design || solving}
              onClick={handleSolvePins}
              className="flex items-center gap-1.5 rounded-md bg-accent-600 px-3 py-1.5 text-xs font-medium text-accent-50 shadow-pop transition-colors enabled:hover:bg-accent-500 disabled:opacity-40"
              title="Auto-assign every unbound connection"
            >
              <Wand2 className="h-4 w-4" />
              {solving ? "Solving..." : "Solve Pins"}
            </button>
          </div>

          {advancedMode && (
            <div className="flex items-center gap-1 border-l border-line pl-3">
              <button
                disabled={!design}
                onClick={() => setShowSchematicDialog(true)}
                className="flex items-center gap-1.5 rounded-md p-1.5 text-xs font-medium text-ink-faint transition-colors enabled:hover:bg-surface-2 enabled:hover:text-ink disabled:opacity-40"
                title="Preview the schematic, download it as .kicad_sch, or export a PCB board"
                aria-label="Schematic (KiCad export)"
              >
                <Cpu className="h-4 w-4" />
              </button>
              <button
                disabled={!design}
                onClick={() => setShowEnclosureDialog(true)}
                className="flex items-center gap-1.5 rounded-md p-1.5 text-xs font-medium text-ink-faint transition-colors enabled:hover:bg-surface-2 enabled:hover:text-ink disabled:opacity-40"
                title="Generate a parametric .scad enclosure shell or search community models"
                aria-label="Enclosure"
              >
                <Box className="h-4 w-4" />
              </button>
              <button
                disabled={!design}
                onClick={() => setShowFleetDialog(true)}
                className="flex items-center gap-1.5 rounded-md p-1.5 text-xs font-medium text-ink-faint transition-colors enabled:hover:bg-surface-2 enabled:hover:text-ink disabled:opacity-40"
                title="Push the rendered YAML to the fleet-for-esphome add-on"
                aria-label="Push to fleet"
              >
                <UploadCloud className="h-4 w-4" />
              </button>
              <button
                onClick={() => setShowFlashDialog(true)}
                className="flex items-center gap-1.5 rounded-md p-1.5 text-xs font-medium text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
                title="Flash firmware over WebSerial (ESPHome, Tasmota, LoRaWAN)"
                aria-label="Flash firmware"
              >
                <Radio className="h-4 w-4" />
              </button>
              <button
                disabled={!design}
                onClick={() => setShowProvisionEsphomeDialog(true)}
                className="flex items-center gap-1.5 rounded-md p-1.5 text-xs font-medium text-ink-faint transition-colors enabled:hover:bg-surface-2 enabled:hover:text-ink disabled:opacity-40"
                title="Provision a LoRaWAN device for the lorawan-for-esphome external-component path"
                aria-label="Provision LoRaWAN device"
              >
                <KeyRound className="h-4 w-4" />
              </button>

              <div className="mx-1 h-4 w-px bg-line"></div>

              <button
                onClick={() => setShowAgent(true)}
                className="flex items-center gap-1.5 rounded-md p-1.5 text-xs font-medium text-agent-300 transition-colors hover:bg-agent-500/10"
                title="Open the design agent"
              >
                <Bot className="h-4 w-4" />
                <span className="hidden lg:inline">Agent</span>
              </button>
            </div>
          )}

          <div className="flex items-center gap-2 border-l border-line pl-3">
            <div className="flex flex-col gap-1">
              <label
                className="flex cursor-pointer items-center gap-1.5 text-[10px] font-medium tracking-wider text-ink-faint transition-colors hover:text-ink"
                title="Strict mode: generation fails when warn/error compatibility entries or design warnings remain. Saved on the design."
              >
                <input
                  type="checkbox"
                  checked={strictMode}
                  onChange={(e) =>
                    setDesign((d) => (d ? { ...d, strict: e.target.checked } : d))
                  }
                  className="h-3 w-3 rounded-sm"
                />
                STRICT
              </label>
              <label
                className="flex cursor-pointer items-center gap-1.5 text-[10px] font-medium tracking-wider text-ink-faint transition-colors hover:text-ink"
                title="Advanced mode reveals Agent, Schematic, Enclosure, and Fleet options"
              >
                <input
                  type="checkbox"
                  checked={advancedMode}
                  onChange={(e) => setAdvancedMode(e.target.checked)}
                  className="h-3 w-3 rounded-sm accent-agent-500"
                />
                ADVANCED
              </label>
            </div>

            <FeedbackLink
              version={version}
              boardId={
                ((design?.board as Record<string, unknown> | undefined)?.library_id as
                  | string
                  | undefined) ?? null
              }
            />

            <button
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              className="ml-1 flex items-center gap-1 rounded-md p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
              title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            >
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>

            <button
              onClick={() => setShowSettingsDialog(true)}
              className="flex items-center gap-1 rounded-md p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
              title="Settings"
              aria-label="Settings"
            >
              <Settings className="h-4 w-4" />
            </button>

            <a
              href="/api/docs" target="_blank" rel="noreferrer"
              className="flex items-center gap-1 rounded-md p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
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
          modules={modules}
          community={community}
          selectedExample={selectedExample}
          selectedCommunity={selectedCommunity}
          onSelectCommunity={handleSelectCommunity}
          selectedSaved={selectedSaved}
          onSelectExample={(id) => { setSelectedSaved(null); setSelectedCommunity(null); setSelectedExample(id); }}
          onSelectSaved={handleSelectSaved}
          onDeleteSaved={handleDeleteSaved}
          onSelectBoard={(id) => setSelection({ kind: "board", id })}
          onSelectComponent={(id) => setSelection({ kind: "component", id })}
          onNewComponent={() => setLibraryEditor({ kind: "component", title: "New component", yaml: NEW_COMPONENT_TEMPLATE, overwrite: false })}
          onNewBoard={() => setLibraryEditor({ kind: "board", title: "New board", yaml: NEW_BOARD_TEMPLATE, overwrite: false })}
          onInsertModule={handleInsertModule}
        />
        <DesignPane design={design} render={render} renderError={renderError} advancedMode={advancedMode} />
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
          onEditComponent={(id, source) => handleEditLibrary("component", id, source)}
          onDeleteComponent={handleDeleteComponent}
          onEditBoard={(id, source) => handleEditLibrary("board", id, source)}
          onDeleteBoard={handleDeleteBoard}
        />
      </main>
      {libraryEditor && (
        <LibraryEditorDialog
          kind={libraryEditor.kind}
          title={libraryEditor.title}
          initialYaml={libraryEditor.yaml}
          overwrite={libraryEditor.overwrite}
          onClose={() => setLibraryEditor(null)}
          onSaved={async (id) => {
            const kind = libraryEditor.kind;
            setLibraryEditor(null);
            await (kind === "board" ? refreshBoards() : refreshComponents());
            setSelection({ kind, id });
          }}
        />
      )}
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
      {showProvisionEsphomeDialog && design && (
        <LorawanProvisionEsphomeDialog
          design={design}
          onClose={() => setShowProvisionEsphomeDialog(false)}
        />
      )}
      {showFlashDialog && (
        <FlashDialog
          design={design}
          boards={boards}
          onClose={() => setShowFlashDialog(false)}
          onOpenFleet={() => setShowFleetDialog(true)}
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
          designBusTypes={designBusTypes}
          onAdd={async (libraryId) => {
            await handleAddComponent(libraryId);
          }}
          onClose={() => setShowCapabilityDialog(false)}
        />
      )}
      {showInventoryDialog && (
        <InventoryDialog
          design={design}
          onClose={() => setShowInventoryDialog(false)}
          onApplyAll={(applied) =>
            setDesign((d) =>
              d
                ? {
                    ...d,
                    part_overrides: {
                      ...((d.part_overrides as Record<string, string> | undefined) ?? {}),
                      ...Object.fromEntries(applied.flatMap((a) => a.keys.map((k) => [k, a.mpn]))),
                    },
                  }
                : d,
            )
          }
          onApplySubstitute={(keys, mpn) =>
            setDesign((d) =>
              d
                ? {
                    ...d,
                    part_overrides: {
                      ...((d.part_overrides as Record<string, string> | undefined) ?? {}),
                      ...Object.fromEntries(keys.map((k) => [k, mpn])),
                    },
                  }
                : d,
            )
          }
        />
      )}
      {showSettingsDialog && <SettingsDialog onClose={() => setShowSettingsDialog(false)} />}
      {showShareDialog && design && communityStatus?.enabled && (
        <ShareDialog design={design} status={communityStatus} onClose={() => setShowShareDialog(false)} />
      )}
      {tokenDialog}
      <AgentSidebar
        open={showAgent}
        design={design}
        onClose={() => setShowAgent(false)}
        onDesignReplaced={handleAgentDesignReplaced}
      />
    </div>
  );
}
