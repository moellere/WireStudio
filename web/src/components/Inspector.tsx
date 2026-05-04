import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { BoardSummary, CompatibilityWarning, ComponentSummary, Design } from "../types/api";
import {
  readComponents,
  readConnections,
  readRequirements,
  readWarnings,
  type ComponentInstance,
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
    <aside className="flex min-h-0 flex-col border-l border-zinc-800">
      <div className="flex items-center gap-2 border-b border-zinc-800 px-4 py-3">
        {selection.kind !== "design" && (
          <button
            onClick={() => onSelect({ kind: "design" })}
            className="rounded border border-zinc-800 px-1.5 py-0.5 text-xs text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
            title="Back to design"
          >
            ←
          </button>
        )}
        <div className="flex-1">
          <div className="text-xs uppercase tracking-wide text-zinc-500">Inspector</div>
          <div className="mt-0.5 truncate text-sm text-zinc-300">
            {selection.kind === "design" && "Design"}
            {selection.kind === "board" && <>Board · <code className="text-zinc-100">{selection.id}</code></>}
            {selection.kind === "component" && <>Library component · <code className="text-zinc-100">{selection.id}</code></>}
            {selection.kind === "component_instance" && <>Instance · <code className="text-zinc-100">{selection.id}</code></>}
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
        {selection.kind === "component" && <LibraryComponentInspector id={selection.id} />}
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
  if (!design) return <div className="text-xs text-zinc-500">No design loaded.</div>;
  const components = readComponents(design);
  const requirements = readRequirements(design);
  const warnings = readWarnings(design);
  const board = (design.board as Record<string, unknown> | undefined) ?? {};
  const fleet = (design.fleet ?? null) as Record<string, unknown> | null;
  const boardRecord = (boardData ?? {}) as Record<string, unknown>;
  const gpioPins = Object.keys((boardRecord.gpio_capabilities ?? {}) as Record<string, unknown>);
  const defaultBuses = (boardRecord.default_buses ?? {}) as Record<string, Record<string, string>>;
  const buses = (design.buses as unknown[] | undefined) ?? [];

  return (
    <div className="space-y-5 text-sm text-zinc-300">
      <Section title="Board">
        <BoardPicker
          currentLibraryId={String(board.library_id ?? "")}
          options={libraryBoards}
          onChange={(libId, mcu) => onDesignChange((d) => setBoardLibraryId(d, libId, mcu))}
        />
      </Section>

      <Section title={`Components (${components.length})`}>
        {components.length === 0 ? (
          <div className="mb-2 text-xs text-zinc-500">no components</div>
        ) : (
          <ul className="mb-2 space-y-1">
            {components.map((c) => (
              <li key={c.id} className="flex items-stretch gap-1">
                <button
                  onClick={() => onSelect({ kind: "component_instance", id: c.id })}
                  className="flex-1 rounded border border-zinc-800 bg-zinc-900/40 px-2 py-1.5 text-left transition-colors hover:bg-zinc-900"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-mono text-xs text-zinc-100">{c.id}</span>
                    <span className="text-[11px] text-zinc-500">{c.library_id}</span>
                  </div>
                  <div className="mt-0.5 truncate text-xs text-zinc-400">{c.label}</div>
                </button>
                <button
                  onClick={() => onRemoveComponent(c.id)}
                  title={`Remove ${c.id}`}
                  className="rounded border border-zinc-800 px-2 text-xs text-zinc-500 transition-colors hover:border-red-500/40 hover:bg-red-500/10 hover:text-red-300"
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
        <AddComponentControl
          libraryComponents={libraryComponents}
          onAdd={onAddComponent}
        />
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
  const options = libraryComponents ?? [];
  // Group by category for the optgroups.
  const byCategory: Record<string, ComponentSummary[]> = {};
  for (const c of options) {
    (byCategory[c.category] ||= []).push(c);
  }
  const categories = Object.keys(byCategory).sort();

  return (
    <div className="flex items-center gap-1">
      <select
        value={picked}
        onChange={(e) => setPicked(e.target.value)}
        className="flex-1 rounded border border-dashed border-zinc-800 bg-zinc-950 px-2 py-1 text-xs text-zinc-300 focus:border-zinc-600 focus:outline-none"
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
        className="rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-300 enabled:hover:bg-zinc-900 disabled:opacity-40"
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
      className="w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
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
        <div key={i} className="rounded border border-zinc-800 bg-zinc-900/40 p-2">
          <div className="mb-1 flex items-center gap-2">
            <select
              value={r.kind}
              onChange={(e) => onUpdate(i, { kind: e.target.value as Requirement["kind"] })}
              className="rounded border border-zinc-800 bg-zinc-950 px-1.5 py-0.5 text-[11px] text-zinc-200"
            >
              {(["capability", "environment", "constraint"] as const).map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
            <span className="font-mono text-[11px] text-zinc-500">{r.id}</span>
            <button
              onClick={() => onRemove(i)}
              className="ml-auto rounded border border-zinc-800 px-1.5 py-0.5 text-[11px] text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
              title="Remove requirement"
            >
              ✕
            </button>
          </div>
          <input
            type="text"
            value={r.text}
            onChange={(e) => onUpdate(i, { text: e.target.value })}
            className="w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
          />
        </div>
      ))}
      <button
        onClick={onAdd}
        className="w-full rounded border border-dashed border-zinc-800 px-2 py-1 text-xs text-zinc-500 hover:border-zinc-700 hover:text-zinc-300"
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
          className={`rounded border p-2 ${
            w.level === "warn"
              ? "border-amber-500/40 bg-amber-500/5"
              : w.level === "error"
                ? "border-red-500/40 bg-red-500/10"
                : "border-zinc-800 bg-zinc-900/40"
          }`}
        >
          <div className="mb-1 flex items-center gap-2">
            <select
              value={w.level}
              onChange={(e) => onUpdate(i, { level: e.target.value as DesignWarning["level"] })}
              className="rounded border border-zinc-800 bg-zinc-950 px-1.5 py-0.5 text-[11px] text-zinc-200"
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
              className="flex-1 rounded border border-zinc-800 bg-zinc-950 px-1.5 py-0.5 font-mono text-[11px] text-zinc-100"
            />
            <button
              onClick={() => onRemove(i)}
              className="rounded border border-zinc-800 px-1.5 py-0.5 text-[11px] text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
              title="Remove warning"
            >
              ✕
            </button>
          </div>
          <textarea
            value={w.text}
            onChange={(e) => onUpdate(i, { text: e.target.value })}
            rows={2}
            className="w-full resize-none rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
          />
        </div>
      ))}
      <button
        onClick={onAdd}
        className="w-full rounded border border-dashed border-zinc-800 px-2 py-1 text-xs text-zinc-500 hover:border-zinc-700 hover:text-zinc-300"
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
      <label className="block text-[11px] text-zinc-500">{label}</label>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="mt-0.5 w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
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
    <div className="space-y-4">
      <div>
        <div className="text-base font-semibold text-zinc-100">{String(b.name)}</div>
        <div className="text-xs text-zinc-500">{String(b.platformio_board)}</div>
      </div>
      <Section title="Identity">
        <KV k="mcu" v={String(b.mcu)} />
        <KV k="chip_variant" v={String(b.chip_variant)} />
        <KV k="framework" v={String(b.framework)} />
        {b.flash_size_mb != null && <KV k="flash" v={`${b.flash_size_mb}MB`} />}
      </Section>
      {rails.length > 0 && (
        <Section title="Rails">
          <ul className="space-y-1 text-xs">
            {rails.map((r, i) => (
              <li key={i} className="font-mono">
                {String(r.name)} <span className="text-zinc-500">({String(r.voltage)}V)</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {Object.keys(gpio).length > 0 && (
        <Section title="GPIO capabilities">
          <ul className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-xs">
            {Object.entries(gpio).map(([pin, caps]) => (
              <li key={pin} className="truncate">
                <span className="text-zinc-100">{pin}</span>
                <span className="text-zinc-500"> {(caps as string[]).join(",")}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

function LibraryComponentInspector({ id }: { id: string }) {
  const comp = useFetched(() => api.getComponent(id), [id]);
  if (!comp) return <Loading />;
  return <FullComponentView comp={comp} />;
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
  const components = readComponents(design);
  const inst = components.find((c) => c.id === instanceId) as ComponentInstance | undefined;
  const comp = useFetched(() => (inst ? api.getComponent(inst.library_id) : Promise.resolve(null)), [inst?.library_id]);

  if (!inst) return <div className="text-xs text-zinc-500">Component not found in design.</div>;
  if (!comp) return <Loading />;

  const c = comp as Record<string, unknown>;
  const schema = (c.params_schema ?? {}) as Record<string, never>;
  const connectionRows = readConnections(design, inst.id);

  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-baseline justify-between gap-2">
          <span className="font-mono text-sm text-zinc-100">{inst.id}</span>
          <span className="rounded border border-zinc-800 px-1.5 py-0.5 text-[11px] text-zinc-400">
            {inst.library_id}
          </span>
        </div>
        <div className="mt-0.5 text-sm text-zinc-300">{inst.label}</div>
        {inst.role && <div className="text-xs text-zinc-500">role: {inst.role}</div>}
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
          <ConnectionForm
            rows={connectionRows}
            design={design}
            boardData={boardData}
            libraryComponents={libraryComponents}
            onChange={onConnectionChange}
            onLockedPinChange={onLockedPinChange}
          />
        ) : null}
      </Section>

      {(() => {
        const mine = compatibilityWarnings.filter((w) => w.component_id === inst.id);
        return mine.length > 0 ? (
          <Section title={`Compatibility (${mine.length})`}>
            <CompatibilityList warnings={mine} />
          </Section>
        ) : null;
      })()}

      <Section title={`From the library (${inst.library_id})`}>
        <FullComponentView comp={comp} compact />
      </Section>
    </div>
  );
}

function FullComponentView({ comp, compact = false }: { comp: unknown; compact?: boolean }) {
  const c = comp as Record<string, unknown>;
  const electrical = (c.electrical ?? {}) as Record<string, unknown>;
  const pins = Array.isArray(electrical.pins) ? electrical.pins as Array<Record<string, unknown>> : [];
  const esphome = (c.esphome ?? {}) as Record<string, unknown>;
  const required = Array.isArray(esphome.required_components) ? esphome.required_components as string[] : [];

  return (
    <div className="space-y-3">
      {!compact && (
        <div>
          <div className="text-base font-semibold text-zinc-100">{String(c.name)}</div>
          <div className="text-xs text-zinc-500">{String(c.category)}</div>
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
          <div className="mb-1 text-[11px] uppercase tracking-wide text-zinc-500">pins</div>
          <ul className="space-y-1 text-xs">
            {pins.map((p, i) => (
              <li key={i} className="font-mono">
                <span className="text-zinc-100">{String(p.role)}</span>
                <span className="text-zinc-500"> · {String(p.kind)}</span>
                {p.voltage != null && <span className="text-zinc-500"> · {String(p.voltage)}V</span>}
                {Boolean(p.pull_up) && <span className="text-amber-300"> · pull-up</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {required.length > 0 && (
        <KV k="required" v={required.join(", ")} />
      )}
      {Boolean(c.notes) && (
        <p className="text-[11px] text-zinc-400">{String(c.notes)}</p>
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
            ? "border-red-500/40 bg-red-500/10 text-red-200"
            : w.severity === "warn"
              ? "border-amber-500/40 bg-amber-500/10 text-amber-100"
              : "border-blue-500/40 bg-blue-500/5 text-blue-100";
        return (
          <li key={i} className={`rounded border px-2 py-1.5 text-xs ${palette}`}>
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
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-500">{title}</h3>
      <div>{children}</div>
    </section>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-xs">
      <span className="text-zinc-500">{k}</span>
      <span className="font-mono text-zinc-200">{v}</span>
    </div>
  );
}

function Loading() {
  return <div className="text-xs text-zinc-500">loading...</div>;
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
