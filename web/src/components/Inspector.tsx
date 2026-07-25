import { useEffect, useState, useMemo } from "react";
import { api } from "../api/client";
import type { BoardSummary, CompatibilityWarning, ComponentSummary, Design } from "../types/api";
import { Cpu, Component as ComponentIcon, LayoutGrid } from "lucide-react";
import { Loading } from "./Status";
import {
  readComponents,
  readConnections,
  readRequirements,
  readWarnings,
  type ComponentInstance,
  type ConnectionRow,
  type ConnectionTarget,
  type DesignWarning,
  type Requirement,
  addRequirement,
  addWarning,
  removeRequirement,
  removeWarning,
  setBoardLibraryId,
  setFleetField,
  updateRequirement,
  updateWarning,
} from "../lib/design";
import { ParamForm } from "./ParamForm";
import { ConnectionForm } from "./ConnectionForm";
import { PinoutView } from "./PinoutView";
import { BusList } from "./BusList";

export type Selection =
  | { kind: "design" }
  | { kind: "board"; id: string }
  | { kind: "component"; id: string }
  | { kind: "component_instance"; id: string };

interface Props {
  selection: Selection;
  design: Design | null;
  boardData: unknown;
  libraryBoards: BoardSummary[] | null;
  libraryComponents: ComponentSummary[] | null;
  compatibilityWarnings: CompatibilityWarning[];
  onSelect: (s: Selection) => void;
  onParamChange: (componentInstanceId: string, paramKey: string, value: unknown) => void;
  onConnectionChange: (connectionIndex: number, target: ConnectionTarget) => void;
  onLockedPinChange: (componentId: string, pinRole: string, pin: string | null) => void;
  onDesignChange: (updater: (d: Design) => Design) => void;
  onAddComponent: (libraryId: string) => void;
  onRemoveComponent: (instanceId: string) => void;
}

export function Inspector({
  selection, design, boardData, libraryBoards, libraryComponents,
  compatibilityWarnings,
  onSelect, onParamChange, onConnectionChange, onLockedPinChange, onDesignChange,
  onAddComponent, onRemoveComponent,
}: Props) {
  return (
    <aside className="flex min-h-0 flex-col border-l border-line bg-surface-0">
      <div className="flex items-center gap-3 border-b border-line px-4 py-3.5 bg-surface-0">
        {selection.kind !== "design" && (
          <button
            onClick={() => onSelect({ kind: "design" })}
            className="flex items-center justify-center rounded-md border border-line p-1.5 text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink"
            title="Back to design"
          >
            ←
          </button>
        )}
        <div className="flex-1">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-ink-faint">Inspector</div>
          <div className="mt-1 flex items-center gap-2 truncate text-sm font-medium text-ink">
            {selection.kind === "design" && <><LayoutGrid className="h-4 w-4 text-ink-dim" /> Design Overview</>}
            {selection.kind === "board" && <><Cpu className="h-4 w-4 text-ink-dim" /> Board Details</>}
            {selection.kind === "component" && <><ComponentIcon className="h-4 w-4 text-ink-dim" /> Library Component</>}
            {selection.kind === "component_instance" && <><ComponentIcon className="h-4 w-4 text-ink-dim" /> Component Instance</>}
          </div>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4 text-sm">
        {selection.kind === "design" && (
          <DesignInspector
            design={design}
            boardData={boardData}
            libraryBoards={libraryBoards}
            libraryComponents={libraryComponents}
            compatibilityWarnings={compatibilityWarnings}
            onSelect={onSelect}
            onDesignChange={onDesignChange}
            onAddComponent={onAddComponent}
            onRemoveComponent={onRemoveComponent}
          />
        )}
        {selection.kind === "board" && <BoardInspector id={selection.id} />}
        {selection.kind === "component" && (
          <LibraryComponentInspector
            id={selection.id}
            designReady={!!design}
            onAdd={onAddComponent}
          />
        )}
        {selection.kind === "component_instance" && (
          <ComponentInstanceInspector
            instanceId={selection.id}
            design={design}
            boardData={boardData}
            libraryComponents={libraryComponents}
            compatibilityWarnings={compatibilityWarnings}
            onParamChange={onParamChange}
            onConnectionChange={onConnectionChange}
            onLockedPinChange={onLockedPinChange}
          />
        )}
      </div>
    </aside>
  );
}

function DesignInspector({
  design, boardData, libraryBoards, libraryComponents, compatibilityWarnings,
  onSelect, onDesignChange, onAddComponent, onRemoveComponent,
}: {
  design: Design | null;
  boardData: unknown;
  libraryBoards: BoardSummary[] | null;
  libraryComponents: ComponentSummary[] | null;
  compatibilityWarnings: CompatibilityWarning[];
  onSelect: (s: Selection) => void;
  onDesignChange: (updater: (d: Design) => Design) => void;
  onAddComponent: (libraryId: string) => void;
  onRemoveComponent: (instanceId: string) => void;
}) {
  const components = useMemo(() => (design ? readComponents(design) : []), [design]);
  const requirements = useMemo(() => (design ? readRequirements(design) : []), [design]);
  const warnings = useMemo(() => (design ? readWarnings(design) : []), [design]);

  if (!design) return <div className="text-xs text-ink-faint">No design loaded.</div>;

  const board = (design.board as Record<string, unknown> | undefined) ?? {};
  const fleet = (design.fleet ?? null) as Record<string, unknown> | null;
  const boardRecord = (boardData ?? {}) as Record<string, unknown>;
  const gpioPins = Object.keys((boardRecord.gpio_capabilities ?? {}) as Record<string, unknown>);
  const defaultBuses = (boardRecord.default_buses ?? {}) as Record<string, Record<string, string>>;
  const buses = (design.buses as unknown[] | undefined) ?? [];

  return (
    <div className="space-y-5 text-sm text-ink-dim">
      <Section title="Board">
        <BoardPicker
          currentLibraryId={String(board.library_id ?? "")}
          options={libraryBoards}
          onChange={(libId, mcu) => onDesignChange((d) => setBoardLibraryId(d, libId, mcu))}
        />
      </Section>

      <Section title={`Components (${components.length})`}>
        <div className="mb-2">
          <AddComponentControl
            libraryComponents={libraryComponents}
            onAdd={onAddComponent}
          />
        </div>
        {components.length === 0 ? (
          <div className="text-xs text-ink-faint">no components</div>
        ) : (
          <ul className="space-y-1">
            {components.map((c) => (
              <li key={c.id} className="flex items-stretch gap-1">
                <button
                  onClick={() => onSelect({ kind: "component_instance", id: c.id })}
                  className="flex-1 rounded-md border border-line bg-surface-2/40 px-2 py-1.5 text-left transition-colors hover:bg-surface-2"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-mono text-xs text-ink">{c.id}</span>
                    <span className="font-mono text-[11px] text-ink-faint">{c.library_id}</span>
                  </div>
                  <div className="mt-0.5 truncate text-xs text-ink-dim">{c.label}</div>
                </button>
                <button
                  onClick={() => onRemoveComponent(c.id)}
                  title={`Remove ${c.id}`}
                  className="rounded-md border border-line px-2 text-xs text-ink-faint transition-colors hover:border-rose-500/40 hover:bg-rose-500/10 hover:text-rose-300"
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={`Buses (${buses.length})`}>
        <BusList
          design={design}
          gpioPins={gpioPins}
          defaultBuses={defaultBuses}
          compatibilityWarnings={compatibilityWarnings}
          onChange={onDesignChange}
        />
      </Section>

      {compatibilityWarnings.length > 0 && (
        <Section title={`Compatibility (${compatibilityWarnings.length})`}>
          <CompatibilityList warnings={compatibilityWarnings} />
        </Section>
      )}

      <Section title={`Requirements (${requirements.length})`}>
        <RequirementList
          items={requirements}
          onUpdate={(i, patch) => onDesignChange((d) => updateRequirement(d, i, patch))}
          onAdd={() => onDesignChange((d) => addRequirement(d))}
          onRemove={(i) => onDesignChange((d) => removeRequirement(d, i))}
        />
      </Section>

      <Section title={`Warnings (${warnings.length})`}>
        <WarningList
          items={warnings}
          onUpdate={(i, patch) => onDesignChange((d) => updateWarning(d, i, patch))}
          onAdd={() => onDesignChange((d) => addWarning(d))}
          onRemove={(i) => onDesignChange((d) => removeWarning(d, i))}
        />
      </Section>

      {fleet && (
        <Section title="Fleet">
          <FleetEditor
            fleet={fleet}
            onChange={(key, value) => onDesignChange((d) => setFleetField(d, key, value))}
          />
        </Section>
      )}
    </div>
  );
}

function AddComponentControl({
  libraryComponents, onAdd,
}: {
  libraryComponents: ComponentSummary[] | null;
  onAdd: (libraryId: string) => void;
}) {
  const [picked, setPicked] = useState<string>("");

  // ⚡ Bolt: memoize category grouping to avoid O(N) allocations and sorting on every render
  const { byCategory, categories } = useMemo(() => {
    const options = libraryComponents ?? [];
    const grouped: Record<string, ComponentSummary[]> = {};
    for (const c of options) {
      (grouped[c.category] ||= []).push(c);
    }
    return {
      byCategory: grouped,
      categories: Object.keys(grouped).sort(),
    };
  }, [libraryComponents]);

  return (
    <div className="space-y-1.5">
      <select
        value={picked}
        onChange={(e) => setPicked(e.target.value)}
        className="w-full min-w-0 max-w-full rounded-md border border-dashed border-line bg-surface-1 px-2 py-1 text-xs text-ink-dim focus:border-accent-500/60 focus:outline-none"
      >
        <option value="">+ Add component...</option>
        {categories.map((cat) => (
          <optgroup key={cat} label={cat}>
            {byCategory[cat].map((c) => (
              <option key={c.id} value={c.id}>{c.name} ({c.id})</option>
            ))}
          </optgroup>
        ))}
      </select>
      <button
        disabled={!picked}
        onClick={() => {
          if (!picked) return;
          onAdd(picked);
          setPicked("");
        }}
        className="w-full rounded-md border border-line px-2 py-1 text-xs text-ink-dim transition-colors enabled:hover:bg-surface-2 enabled:hover:text-ink disabled:opacity-40"
      >
        Add
      </button>
    </div>
  );
}

function BoardPicker({
  currentLibraryId, options, onChange,
}: {
  currentLibraryId: string;
  options: BoardSummary[] | null;
  onChange: (libraryId: string, mcu: string) => void;
}) {
  if (!options) return <Loading />;
  return (
    <select
      value={currentLibraryId}
      onChange={(e) => {
        const next = options.find((b) => b.id === e.target.value);
        if (next) onChange(next.id, next.mcu);
      }}
      className="w-full rounded-md border border-line bg-surface-1 px-2 py-1 text-sm text-ink focus:border-accent-500/60 focus:outline-none"
    >
      {options.map((b) => (
        <option key={b.id} value={b.id}>{b.name} ({b.chip_variant})</option>
      ))}
    </select>
  );
}

function RequirementList({
  items, onUpdate, onAdd, onRemove,
}: {
  items: Requirement[];
  onUpdate: (i: number, patch: Partial<Requirement>) => void;
  onAdd: () => void;
  onRemove: (i: number) => void;
}) {
  return (
    <div className="space-y-2">
      {items.map((r, i) => (
        <div key={i} className="rounded-md border border-line bg-surface-2/40 p-2">
          <div className="mb-1 flex items-center gap-2">
            <select
              value={r.kind}
              onChange={(e) => onUpdate(i, { kind: e.target.value as Requirement["kind"] })}
              className="rounded-md border border-line bg-surface-1 px-1.5 py-0.5 text-[11px] text-ink"
            >
              {(["capability", "environment", "constraint"] as const).map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
            <span className="font-mono text-[11px] text-ink-faint">{r.id}</span>
            <button
              onClick={() => onRemove(i)}
              className="ml-auto rounded-md border border-line px-1.5 py-0.5 text-[11px] text-ink-dim hover:bg-surface-2 hover:text-ink"
              title="Remove requirement"
            >
              ✕
            </button>
          </div>
          <input
            type="text"
            value={r.text}
            onChange={(e) => onUpdate(i, { text: e.target.value })}
            className="w-full rounded-md border border-line bg-surface-1 px-2 py-1 text-xs text-ink focus:border-accent-500/60 focus:outline-none"
          />
        </div>
      ))}
      <button
        onClick={onAdd}
        className="w-full rounded-md border border-dashed border-line px-2 py-1 text-xs text-ink-faint hover:border-line-strong hover:text-ink-dim"
      >
        + Add requirement
      </button>
    </div>
  );
}

function WarningList({
  items, onUpdate, onAdd, onRemove,
}: {
  items: DesignWarning[];
  onUpdate: (i: number, patch: Partial<DesignWarning>) => void;
  onAdd: () => void;
  onRemove: (i: number) => void;
}) {
  return (
    <div className="space-y-2">
      {items.map((w, i) => (
        <div
          key={i}
          className={`rounded-md border p-2 ${
            w.level === "warn"
              ? "border-amber-500/40 bg-amber-500/5"
              : w.level === "error"
                ? "border-rose-500/40 bg-rose-500/10"
                : "border-line bg-surface-2/40"
          }`}
        >
          <div className="mb-1 flex items-center gap-2">
            <select
              value={w.level}
              onChange={(e) => onUpdate(i, { level: e.target.value as DesignWarning["level"] })}
              className="rounded-md border border-line bg-surface-1 px-1.5 py-0.5 text-[11px] text-ink"
            >
              {(["info", "warn", "error"] as const).map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
            <input
              type="text"
              value={w.code}
              onChange={(e) => onUpdate(i, { code: e.target.value })}
              placeholder="code"
              className="flex-1 rounded-md border border-line bg-surface-1 px-1.5 py-0.5 font-mono text-[11px] text-ink"
            />
            <button
              onClick={() => onRemove(i)}
              className="rounded-md border border-line px-1.5 py-0.5 text-[11px] text-ink-dim hover:bg-surface-2 hover:text-ink"
              title="Remove warning"
            >
              ✕
            </button>
          </div>
          <textarea
            value={w.text}
            onChange={(e) => onUpdate(i, { text: e.target.value })}
            rows={2}
            className="w-full resize-none rounded-md border border-line bg-surface-1 px-2 py-1 text-xs text-ink focus:border-accent-500/60 focus:outline-none"
          />
        </div>
      ))}
      <button
        onClick={onAdd}
        className="w-full rounded-md border border-dashed border-line px-2 py-1 text-xs text-ink-faint hover:border-line-strong hover:text-ink-dim"
      >
        + Add warning
      </button>
    </div>
  );
}

function FleetEditor({
  fleet, onChange,
}: {
  fleet: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  const tags = Array.isArray(fleet.tags) ? (fleet.tags as string[]).join(", ") : "";
  return (
    <div className="space-y-2 text-xs">
      <Field
        label="device_name"
        value={String(fleet.device_name ?? "")}
        onChange={(v) => onChange("device_name", v)}
      />
      <Field
        label="tags"
        placeholder="comma-separated"
        value={tags}
        onChange={(v) =>
          onChange("tags", v.split(",").map((s) => s.trim()).filter(Boolean))
        }
      />
    </div>
  );
}

function Field({
  label, value, onChange, placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="block text-[11px] text-ink-faint">{label}</label>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="mt-0.5 w-full rounded-md border border-line bg-surface-1 px-2 py-1 text-xs text-ink focus:border-accent-500/60 focus:outline-none"
      />
    </div>
  );
}

function BoardInspector({ id }: { id: string }) {
  const board = useFetched(() => api.getBoard(id), [id]);
  if (!board) return <Loading />;
  const b = board as Record<string, unknown>;
  const rails = Array.isArray(b.rails) ? b.rails as Array<Record<string, unknown>> : [];
  const gpio = (b.gpio_capabilities ?? {}) as Record<string, string[]>;
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-base font-semibold text-ink">{String(b.name)}</h2>
        <div className="mt-1 flex items-center gap-2 text-xs text-ink-faint">
          <span className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono font-medium">{String(b.chip_variant)}</span>
          <span>·</span>
          <span>{String(b.framework)}</span>
          {Boolean(b.flash_size_mb) && (
            <div className="flex items-center gap-2">
              <span>·</span>
              <span>{String(b.flash_size_mb)}MB Flash</span>
            </div>
          )}
        </div>
      </div>

      <div className="space-y-3 rounded-md border border-line bg-surface-2/40 p-4 text-xs">
        <div className="flex justify-between items-center border-b border-line/50 pb-2">
          <span className="text-ink-faint font-medium">PlatformIO ID</span>
          <span className="font-mono text-ink-dim">{b.platformio_board ? String(b.platformio_board) : "Unknown"}</span>
        </div>
        <div className="flex justify-between items-center border-b border-line/50 pb-2">
          <span className="text-ink-faint font-medium">MCU Family</span>
          <span className="font-mono text-ink-dim">{b.mcu ? String(b.mcu) : "Unknown"}</span>
        </div>
      </div>

      {rails.length > 0 && (
        <Section title="Power Rails">
          <div className="rounded-md border border-line bg-surface-2/40 overflow-hidden">
            <ul className="divide-y divide-line/50 text-xs">
              {rails.map((r, i) => (
                <li key={i} className="flex justify-between px-3 py-2">
                  <span className="font-mono font-medium text-ink">{String(r.name)}</span>
                  <span className="text-ink-dim">{String(r.voltage)}V</span>
                </li>
              ))}
            </ul>
          </div>
        </Section>
      )}

      {Object.keys(gpio).length > 0 && (
        <Section title="GPIO Capabilities">
          <ul className="grid grid-cols-2 gap-x-3 gap-y-2 font-mono text-xs">
            {Object.entries(gpio).map(([pin, caps]) => (
              <li key={pin} className="flex flex-col gap-1 rounded-md bg-surface-2/40 p-2 border border-line/50">
                <span className="font-medium text-ink">{pin}</span>
                <span className="text-[10px] text-ink-faint leading-tight">{(caps as string[]).join(", ")}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

function LibraryComponentInspector({
  id, designReady, onAdd,
}: {
  id: string;
  designReady: boolean;
  onAdd: (libraryId: string) => void;
}) {
  const comp = useFetched(() => api.getComponent(id), [id]);
  if (!comp) return <Loading />;

  const c = comp as Record<string, unknown>;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-base font-semibold text-ink">{String(c.name)}</h2>
        <div className="mt-2 flex items-center gap-2 text-xs text-ink-faint">
          <span className="rounded-md bg-surface-2 px-2 py-0.5 uppercase tracking-wider text-[10px] font-medium text-ink-dim">
            {String(c.category)}
          </span>
        </div>
      </div>

      <button
        disabled={!designReady}
        onClick={() => onAdd(id)}
        title={designReady ? "Add this component to the open design" : "Open or create a design first"}
        className="w-full rounded-md bg-accent-600 px-3 py-1.5 text-xs font-medium text-accent-50 shadow-pop transition-colors enabled:hover:bg-accent-500 disabled:opacity-40"
      >
        Add to design
      </button>

      <div className="rounded-md border border-line bg-surface-2/40 p-4 text-xs">
        {c.notes ? (
          <div className="text-ink-dim leading-relaxed">{String(c.notes)}</div>
        ) : (
          <div className="text-ink-faint italic">No notes for this component.</div>
        )}
      </div>

      <FullComponentView comp={comp} compact hideNotes />
    </div>
  );
}

function ComponentInstanceInspector({
  instanceId, design, boardData, libraryComponents, compatibilityWarnings,
  onParamChange, onConnectionChange, onLockedPinChange,
}: {
  instanceId: string;
  design: Design | null;
  boardData: unknown;
  libraryComponents: ComponentSummary[] | null;
  compatibilityWarnings: CompatibilityWarning[];
  onParamChange: (componentInstanceId: string, paramKey: string, value: unknown) => void;
  onConnectionChange: (connectionIndex: number, target: ConnectionTarget) => void;
  onLockedPinChange: (componentId: string, pinRole: string, pin: string | null) => void;
}) {
  const components = useMemo(() => (design ? readComponents(design) : []), [design]);
  const connectionRows = useMemo(() => (design ? readConnections(design, instanceId) : []), [design, instanceId]);

  // ⚡ Bolt: memoize instance lookup to prevent O(N) traversal on every render
  const inst = useMemo(() => {
    return components.find((c) => c.id === instanceId) as ComponentInstance | undefined;
  }, [components, instanceId]);
  const comp = useFetched(() => (inst ? api.getComponent(inst.library_id) : Promise.resolve(null)), [inst?.library_id]);

  // ⚡ Bolt: memoize component-specific warnings to avoid O(N) array allocation on every render
  const mineWarnings = useMemo(() => {
    if (!inst) return [];
    return compatibilityWarnings.filter((w) => w.component_id === inst.id);
  }, [compatibilityWarnings, inst]);

  if (!inst) return <div className="text-xs text-ink-faint">Component not found in design.</div>;
  if (!comp) return <Loading />;

  const c = comp as Record<string, unknown>;
  const schema = (c.params_schema ?? {}) as Record<string, never>;

  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-baseline justify-between gap-2">
          <span className="font-mono text-sm text-ink">{inst.id}</span>
          <span className="rounded-md border border-line px-1.5 py-0.5 font-mono text-[11px] text-ink-dim">
            {inst.library_id}
          </span>
        </div>
        <div className="mt-0.5 text-sm text-ink-dim">{inst.label}</div>
        {inst.role && <div className="text-xs text-ink-faint">role: {inst.role}</div>}
      </div>

      <Section title="Parameters">
        <ParamForm
          schema={schema}
          values={inst.params ?? {}}
          onChange={(key, value) => onParamChange(inst.id, key, value)}
        />
      </Section>

      <Section title="Connections">
        {design ? (
          <ConnectionsPane
            rows={connectionRows}
            design={design}
            boardData={boardData}
            instance={inst}
            libraryComponents={libraryComponents}
            onConnectionChange={onConnectionChange}
            onLockedPinChange={onLockedPinChange}
          />
        ) : null}
      </Section>

      {mineWarnings.length > 0 ? (
        <Section title={`Compatibility (${mineWarnings.length})`}>
          <CompatibilityList warnings={mineWarnings} />
        </Section>
      ) : null}

      <Section title={`From the library (${inst.library_id})`}>
        <FullComponentView comp={comp} compact />
      </Section>
    </div>
  );
}

/**
 * View toggle wrapping the Form-based ConnectionForm and the drag-and-
 * drop PinoutView. Form is the default since it covers every target
 * kind (rail/gpio/bus/expander_pin/component); Pinout is a faster
 * gpio-only surface for board-pin-heavy designs.
 */
function ConnectionsPane({
  rows, design, boardData, instance, libraryComponents,
  onConnectionChange, onLockedPinChange,
}: {
  rows: ConnectionRow[];
  design: Design;
  boardData: unknown;
  instance: ComponentInstance;
  libraryComponents: ComponentSummary[] | null;
  onConnectionChange: (connectionIndex: number, target: ConnectionTarget) => void;
  onLockedPinChange: (componentId: string, pinRole: string, pin: string | null) => void;
}) {
  const [view, setView] = useState<"form" | "pinout">("form");
  const board = (boardData ?? {}) as Record<string, unknown>;
  const gpioCapabilities = (board.gpio_capabilities ?? {}) as Record<string, string[]>;
  const allConnections = useMemo(() => (design ? readConnections(design) : []), [design]);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1 text-[11px]">
        {(["form", "pinout"] as const).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setView(v)}
            className={`rounded-md px-1.5 py-0.5 transition-colors ${
              view === v
                ? "bg-surface-2 text-ink"
                : "text-ink-faint hover:text-ink"
            }`}
          >
            {v === "form" ? "Form" : "Pinout"}
          </button>
        ))}
      </div>
      {view === "form" ? (
        <ConnectionForm
          rows={rows}
          design={design}
          boardData={boardData}
          libraryComponents={libraryComponents}
          onChange={onConnectionChange}
          onLockedPinChange={onLockedPinChange}
        />
      ) : (
        <PinoutView
          rows={rows}
          allConnections={allConnections}
          instance={instance}
          gpioCapabilities={gpioCapabilities}
          onChange={onConnectionChange}
        />
      )}
    </div>
  );
}


function FullComponentView(
  { comp, compact = false, hideNotes = false }:
  { comp: unknown; compact?: boolean; hideNotes?: boolean },
) {
  const c = comp as Record<string, unknown>;
  const electrical = (c.electrical ?? {}) as Record<string, unknown>;
  const pins = Array.isArray(electrical.pins) ? electrical.pins as Array<Record<string, unknown>> : [];
  const esphome = (c.esphome ?? {}) as Record<string, unknown>;
  const required = Array.isArray(esphome.required_components) ? esphome.required_components as string[] : [];

  return (
    <div className="space-y-3">
      {!compact && (
        <div>
          <div className="text-base font-semibold text-ink">{String(c.name)}</div>
          <div className="text-xs text-ink-faint">{String(c.category)}</div>
        </div>
      )}
      <div>
        {electrical.vcc_min != null && (
          <KV k="VCC" v={`${electrical.vcc_min} – ${electrical.vcc_max}V`} />
        )}
        {electrical.current_ma_typical != null && (
          <KV k="current" v={`${electrical.current_ma_typical} typ / ${electrical.current_ma_peak} peak mA`} />
        )}
      </div>
      {pins.length > 0 && (
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wider text-ink-faint">pins</div>
          <ul className="space-y-1 text-xs">
            {pins.map((p, i) => (
              <li key={i} className="font-mono">
                <span className="text-ink">{String(p.role)}</span>
                <span className="text-ink-faint"> · {String(p.kind)}</span>
                {p.voltage != null && <span className="text-ink-faint"> · {String(p.voltage)}V</span>}
                {Boolean(p.pull_up) && <span className="text-amber-300"> · pull-up</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {required.length > 0 && (
        <KV k="required" v={required.join(", ")} />
      )}
      {!hideNotes && Boolean(c.notes) && (
        <p className="text-[11px] text-ink-dim">{String(c.notes)}</p>
      )}
    </div>
  );
}

function CompatibilityList({ warnings }: { warnings: CompatibilityWarning[] }) {
  return (
    <ul className="space-y-1.5">
      {warnings.map((w, i) => {
        const palette =
          w.severity === "error"
            ? "border-rose-500/40 bg-rose-500/10 text-rose-200"
            : w.severity === "warn"
              ? "border-amber-500/40 bg-amber-500/10 text-amber-100"
              : "border-accent-500/40 bg-accent-500/5 text-accent-200";
        return (
          <li key={i} className={`rounded-md border px-2 py-1.5 text-xs ${palette}`}>
            <div className="flex items-baseline justify-between gap-2 font-mono">
              <span>[{w.severity}] {w.code}</span>
              <span className="text-[11px] opacity-80">
                {w.pin} · {w.component_id}.{w.pin_role}
              </span>
            </div>
            <div className="mt-1">{w.message}</div>
          </li>
        );
      })}
    </ul>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-ink-faint">{title}</h3>
      <div>{children}</div>
    </section>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-xs">
      <span className="text-ink-faint">{k}</span>
      <span className="font-mono text-ink">{v}</span>
    </div>
  );
}

function useFetched<T>(fn: () => Promise<T>, deps: unknown[]): T | null {
  const [v, setV] = useState<T | null>(null);
  useEffect(() => {
    let cancelled = false;
    setV(null);
    fn().then((r) => { if (!cancelled) setV(r); }).catch(() => { /* swallow for now */ });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return v;
}
