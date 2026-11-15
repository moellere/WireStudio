import { useEffect, useState, useMemo } from "react";
import { api } from "../api/client";
import type { BoardSummary, CompatibilityWarning, ComponentSummary, Design } from "../types/api";
import { Cpu, Component as ComponentIcon, LayoutGrid } from "lucide-react";
import { Loading } from "./Status";
import {
  readComponents,
  readConnections,
  readRequirements,
  type ComponentInstance,
  type ConnectionRow,
  type ConnectionTarget,
  type Requirement,
  addRequirement,
  removeRequirement,
  setBoardFlashSize,
  setBoardLibraryId,
  setBoardRevision,
  FLASH_SIZE_OVERRIDES_MB,
  setFleetField,
  updateRequirement,
} from "../lib/design";
import { ParamForm } from "./ParamForm";
import { ConnectionForm } from "./ConnectionForm";
import { PinoutView } from "./PinoutView";
import { BusList } from "./BusList";
import { Button, Chip, Input, KeyValueRow, Section, Select } from "./ui";

const REMOVE_BUTTON =
  "flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-md border border-line text-xs text-ink-faint " +
  "transition-colors hover:border-rose-500/40 hover:bg-rose-500/10 hover:text-rose-300";

export type Selection =
  | { kind: "design" }
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
  /** Opens the capability picker. */
  onAddByFunction?: () => void;
  /** Opens the problems panel on its Compatibility tab. */
  onShowProblems?: () => void;
}

export function Inspector({
  selection, design, boardData, libraryBoards, libraryComponents,
  compatibilityWarnings,
  onSelect, onParamChange, onConnectionChange, onLockedPinChange, onDesignChange,
  onAddComponent, onRemoveComponent, onAddByFunction, onShowProblems,
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
            onAddByFunction={onAddByFunction}
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
            onShowProblems={onShowProblems}
          />
        )}
      </div>
    </aside>
  );
}

function DesignInspector({
  design, boardData, libraryBoards, libraryComponents, compatibilityWarnings,
  onSelect, onDesignChange, onAddComponent, onRemoveComponent, onAddByFunction,
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
  onAddByFunction?: () => void;
}) {
  const components = useMemo(() => (design ? readComponents(design) : []), [design]);
  const requirements = useMemo(() => (design ? readRequirements(design) : []), [design]);

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
        <RevisionPicker
          libraryBoard={libraryBoards?.find((b) => b.id === board.library_id)}
          revision={typeof board.revision === "string" ? board.revision : null}
          onChange={(rev) => onDesignChange((d) => setBoardRevision(d, rev))}
        />
        <FlashSizeOverride
          libraryBoard={libraryBoards?.find((b) => b.id === board.library_id)}
          override={typeof board.flash_size_mb === "number" ? board.flash_size_mb : null}
          onChange={(size) => onDesignChange((d) => setBoardFlashSize(d, size))}
        />
      </Section>

      <Section title={`Components (${components.length})`}>
        {components.length === 0 ? (
          <div className="text-xs text-ink-faint">no components</div>
        ) : (
          <ul className="space-y-1">
            {components.map((c) => (
              <li key={c.id} className="flex items-center gap-1">
                <button
                  onClick={() => onSelect({ kind: "component_instance", id: c.id })}
                  title={`${c.label} (${c.library_id})`}
                  className="flex h-[26px] min-w-0 flex-1 items-center gap-2 rounded-md border border-line bg-surface-2/40 px-2 text-left text-xs transition-colors hover:bg-surface-2"
                >
                  <span className="shrink-0 font-mono text-ink">{c.id}</span>
                  <span className="min-w-0 flex-1 truncate text-ink-dim">{c.label}</span>
                  <span className="shrink-0 font-mono text-[11px] text-ink-faint">{c.library_id}</span>
                </button>
                <button onClick={() => onRemoveComponent(c.id)} title={`Remove ${c.id}`} className={REMOVE_BUTTON}>
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-1.5">
          <AddComponentControl
            libraryComponents={libraryComponents}
            onAdd={onAddComponent}
            onAddByFunction={onAddByFunction}
          />
        </div>
      </Section>

      <Section title={`Buses (${buses.length})`}>
        <BusList
          design={design}
          gpioPins={gpioPins}
          gpioCaps={(boardRecord.gpio_capabilities ?? {}) as Record<string, string[]>}
          defaultBuses={defaultBuses}
          compatibilityWarnings={compatibilityWarnings}
          onChange={onDesignChange}
        />
      </Section>

      <Section title={`Requirements (${requirements.length})`}>
        <RequirementList
          items={requirements}
          onUpdate={(i, patch) => onDesignChange((d) => updateRequirement(d, i, patch))}
          onAdd={() => onDesignChange((d) => addRequirement(d))}
          onRemove={(i) => onDesignChange((d) => removeRequirement(d, i))}
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
  libraryComponents, onAdd, onAddByFunction,
}: {
  libraryComponents: ComponentSummary[] | null;
  onAdd: (libraryId: string) => void;
  onAddByFunction?: () => void;
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
    <div className="flex items-center gap-1.5">
      <Select
        aria-label="Component to add"
        value={picked}
        onChange={(e) => setPicked(e.target.value)}
        className="flex-1 text-ink-dim"
      >
        <option value="">Add component...</option>
        {categories.map((cat) => (
          <optgroup key={cat} label={cat}>
            {byCategory[cat].map((c) => (
              <option key={c.id} value={c.id}>{c.name} ({c.id})</option>
            ))}
          </optgroup>
        ))}
      </Select>
      <Button
        size="sm"
        className="h-[26px] shrink-0"
        disabled={!picked}
        onClick={() => {
          if (!picked) return;
          onAdd(picked);
          setPicked("");
        }}
      >
        Add
      </Button>
      {onAddByFunction && (
        <Button
          variant="ghost"
          size="sm"
          className="h-[26px] shrink-0 whitespace-nowrap"
          onClick={onAddByFunction}
          title="Pick a capability and add a matching component"
        >
          By function
        </Button>
      )}
    </div>
  );
}

function RevisionPicker({
  libraryBoard, revision, onChange,
}: {
  libraryBoard: BoardSummary | undefined;
  revision: string | null;
  onChange: (revision: string | null) => void;
}) {
  if (!libraryBoard?.revisions.length) return null;
  return (
    <div className="mt-1.5">
      <div className="flex items-center gap-2">
        <label htmlFor="board-revision" className="w-[4.5rem] shrink-0 text-[11px] text-ink-faint">
          revision
        </label>
        <Select
          id="board-revision"
          value={revision ?? ""}
          onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
          className="flex-1"
        >
          <option value="">Board default</option>
          {libraryBoard.revisions.map((rev) => (
            <option key={rev} value={rev}>{rev}</option>
          ))}
        </Select>
      </div>
      {revision === null && (
        <p className="mt-1 text-[11px] text-amber-300">
          This board's wiring differs by revision. Read it off the silkscreen;
          the default is the board file's wiring.
        </p>
      )}
    </div>
  );
}

function FlashSizeOverride({
  libraryBoard, override, onChange,
}: {
  libraryBoard: BoardSummary | undefined;
  override: number | null;
  onChange: (sizeMb: number | null) => void;
}) {
  // Mirrors the backend: only ESP32-family boards emit a flash size.
  if (!libraryBoard?.chip_variant.startsWith("esp32")) return null;
  const boardSize = libraryBoard.flash_size_mb;
  const raised = override !== null && boardSize !== null && override > boardSize;
  return (
    <div className="mt-1.5">
      <div className="flex items-center gap-2">
        <label htmlFor="flash-size-override" className="w-[4.5rem] shrink-0 text-[11px] text-ink-faint">
          flash size
        </label>
        <Select
          id="flash-size-override"
          value={override === null ? "" : String(override)}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
          className="flex-1"
        >
          <option value="">
            {boardSize ? `Board default (${boardSize}MB)` : "Board default"}
          </option>
          {FLASH_SIZE_OVERRIDES_MB.map((mb) => (
            <option key={mb} value={mb}>{mb}MB</option>
          ))}
        </Select>
      </div>
      {raised && (
        <p className="mt-1 text-[11px] text-amber-300">
          Above the board file's {boardSize}MB. Declaring more flash than the
          chip has boot-loops it. Confirm with <code>esptool flash-id</code> or
          the bootloader's "SPI Flash Size" line first.
        </p>
      )}
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
    <Select
      aria-label="Board"
      value={currentLibraryId}
      onChange={(e) => {
        const next = options.find((b) => b.id === e.target.value);
        if (next) onChange(next.id, next.mcu);
      }}
    >
      {options.map((b) => (
        <option key={b.id} value={b.id}>{b.name} ({b.chip_variant})</option>
      ))}
    </Select>
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
    <div className="space-y-1">
      {items.map((r, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <span className="w-5 shrink-0 font-mono text-[11px] text-ink-faint">{r.id}</span>
          <Select
            aria-label={`${r.id} kind`}
            value={r.kind}
            onChange={(e) => onUpdate(i, { kind: e.target.value as Requirement["kind"] })}
            className="w-[6.5rem] shrink-0"
          >
            {(["capability", "environment", "constraint"] as const).map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </Select>
          <Input
            compact
            type="text"
            aria-label={`${r.id} text`}
            title={r.text}
            value={r.text}
            onChange={(e) => onUpdate(i, { text: e.target.value })}
            className="flex-1"
          />
          <button onClick={() => onRemove(i)} className={REMOVE_BUTTON} title="Remove requirement">
            ✕
          </button>
        </div>
      ))}
      <button
        onClick={onAdd}
        className="h-[26px] w-full rounded-md border border-dashed border-line px-2 text-xs text-ink-faint hover:border-line-strong hover:text-ink-dim"
      >
        + Add requirement
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
    <div className="space-y-1 text-xs">
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
    <div className="flex items-center gap-2">
      <label htmlFor={`fleet-${label}`} className="w-[4.5rem] shrink-0 text-[11px] text-ink-faint">{label}</label>
      <Input
        compact
        id={`fleet-${label}`}
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="flex-1"
      />
    </div>
  );
}

export type LibraryPageTarget = { kind: "board" | "component"; id: string };

export function LibraryPage({
  page, libraryBoards, libraryComponents, designReady, onBack,
  onAddComponent, onEditComponent, onDeleteComponent, onEditBoard, onDeleteBoard, onShareLibrary,
}: {
  page: LibraryPageTarget;
  libraryBoards: BoardSummary[] | null;
  libraryComponents: ComponentSummary[] | null;
  designReady: boolean;
  onBack: () => void;
  onAddComponent: (libraryId: string) => void;
  onEditComponent: (libraryId: string, source: "bundled" | "user") => void;
  onDeleteComponent: (libraryId: string) => void;
  onEditBoard: (libraryId: string, source: "bundled" | "user") => void;
  onDeleteBoard: (libraryId: string) => void;
  /** Share a user entry to the community catalogue; absent when it is off. */
  onShareLibrary?: (kind: "components" | "boards", libraryId: string) => void;
}) {
  const Icon = page.kind === "board" ? Cpu : ComponentIcon;
  return (
    <section className="flex min-h-0 min-w-0 flex-col">
      <div className="flex items-center gap-3 border-b border-line px-4 py-2.5">
        <button
          onClick={onBack}
          className="rounded-md border border-line px-2 py-1 text-xs text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink"
        >
          {designReady ? "← Back to design" : "← Back"}
        </button>
        <Icon className="h-4 w-4 text-ink-dim" />
        <span className="text-xs font-semibold uppercase tracking-wider text-ink-faint">
          {page.kind === "board" ? "Library board" : "Library component"}
        </span>
        <span className="font-mono text-xs text-ink-dim">{page.id}</span>
        <div className="ml-auto flex items-center gap-2">
          {page.kind === "board" ? (
            <LibraryEntryActions
              kind="board"
              id={page.id}
              source={libraryBoards?.find((b) => b.id === page.id)?.source ?? "bundled"}
              onEdit={onEditBoard}
              onDelete={onDeleteBoard}
              onShare={onShareLibrary && ((id) => onShareLibrary("boards", id))}
            />
          ) : (
            <>
              <LibraryEntryActions
                kind="component"
                id={page.id}
                source={libraryComponents?.find((c) => c.id === page.id)?.source ?? "bundled"}
                onEdit={onEditComponent}
                onDelete={onDeleteComponent}
                onShare={onShareLibrary && ((id) => onShareLibrary("components", id))}
              />
              <Button
                variant="primary"
                disabled={!designReady}
                onClick={() => onAddComponent(page.id)}
                title={designReady ? "Add this component to the open design" : "Open or create a design first"}
              >
                Add to design
              </Button>
            </>
          )}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <div className={`p-6 text-sm ${page.kind === "board" ? "max-w-3xl" : "max-w-xl"}`}>
          {page.kind === "board" ? (
            <BoardInspector id={page.id} />
          ) : (
            <LibraryComponentInspector id={page.id} />
          )}
        </div>
      </div>
    </section>
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
          <Chip variant="mcu">{String(b.chip_variant)}</Chip>
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

function LibraryEntryActions({
  kind, id, source, onEdit, onDelete, onShare,
}: {
  kind: "component" | "board";
  id: string;
  source: "bundled" | "user";
  onEdit: (libraryId: string, source: "bundled" | "user") => void;
  onDelete: (libraryId: string) => void;
  onShare?: (libraryId: string) => void;
}) {
  return (
    <>
      {source === "user" && (
        <Button variant="danger" onClick={() => onDelete(id)} title="Remove from the user library">
          Delete
        </Button>
      )}
      {source === "user" && onShare && (
        <Button onClick={() => onShare(id)} title={`Share this ${kind} to the community library`}>
          Share
        </Button>
      )}
      <Button
        onClick={() => onEdit(id, source)}
        title={source === "user" ? `Edit this ${kind}'s YAML` : `Start a new ${kind} from this one's YAML`}
      >
        {source === "user" ? "Edit YAML" : "Copy as new"}
      </Button>
    </>
  );
}

function LibraryComponentInspector({ id }: { id: string }) {
  const comp = useFetched(() => api.getComponent(id), [id]);
  if (!comp) return <Loading />;

  const c = comp as Record<string, unknown>;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-base font-semibold text-ink">{String(c.name)}</h2>
        <div className="mt-2 flex items-center gap-2 text-xs text-ink-faint">
          <Chip variant="category">{String(c.category)}</Chip>
        </div>
      </div>

      <div className="rounded-md border border-line bg-surface-2/40 p-4 text-xs">
        {c.notes ? (
          <div className="text-ink-dim leading-relaxed">{String(c.notes)}</div>
        ) : (
          <div className="text-ink-faint italic">No notes for this component.</div>
        )}
      </div>

      <div className="max-w-sm">
        <FullComponentView comp={comp} compact hideNotes />
      </div>
    </div>
  );
}

function ComponentInstanceInspector({
  instanceId, design, boardData, libraryComponents, compatibilityWarnings,
  onParamChange, onConnectionChange, onLockedPinChange, onShowProblems,
}: {
  instanceId: string;
  design: Design | null;
  boardData: unknown;
  libraryComponents: ComponentSummary[] | null;
  compatibilityWarnings: CompatibilityWarning[];
  onParamChange: (componentInstanceId: string, paramKey: string, value: unknown) => void;
  onConnectionChange: (connectionIndex: number, target: ConnectionTarget) => void;
  onLockedPinChange: (componentId: string, pinRole: string, pin: string | null) => void;
  onShowProblems?: () => void;
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

      {mineWarnings.length > 0 && (
        <CompatibilitySummary warnings={mineWarnings} onShowProblems={onShowProblems} />
      )}

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

      <DiscretePartsSection design={design} instanceId={inst.id} />

      <Section title={`From the library (${inst.library_id})`}>
        <FullComponentView comp={comp} compact />
      </Section>
    </div>
  );
}

/** The checker's findings for one component, one line each; the messages live in the problems panel. */
function CompatibilitySummary({
  warnings, onShowProblems,
}: { warnings: CompatibilityWarning[]; onShowProblems?: () => void }) {
  const tone = warnings.some((w) => w.severity === "error")
    ? "border-rose-500/40 bg-rose-500/10 text-rose-200"
    : warnings.some((w) => w.severity === "warn")
      ? "border-amber-500/40 bg-amber-500/10 text-amber-100"
      : "border-accent-500/40 bg-accent-500/5 text-accent-200";
  return (
    <div className={`rounded-md border px-2 py-1.5 text-xs ${tone}`}>
      <ul className="space-y-0.5 font-mono text-[11px]">
        {warnings.map((w, i) => (
          <li key={i} className="flex items-baseline justify-between gap-2" title={w.message}>
            <span className="truncate">[{w.severity}] {w.code}</span>
            <span className="shrink-0 opacity-80">{w.pin} · {w.pin_role}</span>
          </li>
        ))}
      </ul>
      {onShowProblems && (
        <button onClick={onShowProblems} className="mt-1 text-[11px] underline hover:no-underline">
          Show in Problems
        </button>
      )}
    </div>
  );
}

/**
 * View toggle wrapping the Form-based ConnectionForm and the drag-and-
 * drop PinoutView. Form is the default since it covers every target
 * kind (rail/gpio/bus/expander_pin/component/net); Pinout is a faster
 * gpio-only surface for board-pin-heavy designs.
 */
/**
 * The discrete parts a component expands into on the board. Components
 * with a `subcircuit:` block (the H-bridges) emit a dozen-plus
 * designators that the schematic, PCB and BOM all carry but the
 * inspector used to hide, showing one line for fifteen parts.
 *
 * Designators come from the server because they are design-global:
 * adding a component upstream renumbers everything after it.
 */
function DiscretePartsSection({
  design, instanceId,
}: { design: Design | null; instanceId: string }) {
  // Refs depend on the component set and its order, not on params, so
  // editing a parameter must not refetch.
  const signature = useMemo(
    () => (design ? readComponents(design).map((c) => `${c.id}:${c.library_id}`).join(",") : ""),
    [design],
  );
  const data = useFetched(
    () => (design ? api.designParts(design) : Promise.resolve(null)),
    [signature],
  );
  const mine = useMemo(
    () => (data?.parts ?? []).filter((p) => p.component_id === instanceId && p.part_id),
    [data, instanceId],
  );
  if (mine.length === 0) return null;

  return (
    <Section title={`Discrete parts (${mine.length})`}>
      <ul className="space-y-1">
        {mine.map((p) => (
          <li
            key={p.ref}
            className="flex items-baseline gap-2 rounded-md border border-line bg-surface-2/40 px-2 py-1"
          >
            <span className="w-10 shrink-0 font-mono text-xs text-ink">{p.ref}</span>
            <span className="font-mono text-xs text-ink-dim">{p.value || p.part_id}</span>
            <span className="ml-auto truncate text-[10px] text-ink-faint" title={p.footprint}>
              {p.footprint.split(":").pop()}
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-1 text-[10px] text-ink-faint">
        These land on the schematic, PCB and BOM under these designators.
      </div>
    </Section>
  );
}

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
          <KeyValueRow k="VCC" v={`${electrical.vcc_min} – ${electrical.vcc_max}V`} />
        )}
        {electrical.current_ma_typical != null && (
          <KeyValueRow k="current" v={`${electrical.current_ma_typical} typ / ${electrical.current_ma_peak} peak mA`} />
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
        <KeyValueRow k="required" v={required.join(", ")} />
      )}
      {!hideNotes && Boolean(c.notes) && (
        <p className="text-[11px] text-ink-dim">{String(c.notes)}</p>
      )}
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
