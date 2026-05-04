import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Design } from "../types/api";
import { readComponents, type ComponentInstance } from "../lib/design";
import { ParamForm } from "./ParamForm";

export type Selection =
  | { kind: "design" }
  | { kind: "board"; id: string }
  | { kind: "component"; id: string }
  | { kind: "component_instance"; id: string };

interface Props {
  selection: Selection;
  design: Design | null;
  onSelect: (s: Selection) => void;
  onParamChange: (componentInstanceId: string, paramKey: string, value: unknown) => void;
}

export function Inspector({ selection, design, onSelect, onParamChange }: Props) {
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
          <DesignInspector design={design} onSelect={onSelect} />
        )}
        {selection.kind === "board" && <BoardInspector id={selection.id} />}
        {selection.kind === "component" && <LibraryComponentInspector id={selection.id} />}
        {selection.kind === "component_instance" && (
          <ComponentInstanceInspector
            instanceId={selection.id}
            design={design}
            onParamChange={onParamChange}
          />
        )}
      </div>
    </aside>
  );
}

function DesignInspector({
  design, onSelect,
}: {
  design: Design | null;
  onSelect: (s: Selection) => void;
}) {
  if (!design) return <div className="text-xs text-zinc-500">No design loaded.</div>;
  const components = readComponents(design);
  const requirements = Array.isArray(design.requirements) ? design.requirements as Array<Record<string, unknown>> : [];
  const warnings = Array.isArray(design.warnings) ? design.warnings as Array<Record<string, unknown>> : [];
  const fleet = (design.fleet ?? null) as Record<string, unknown> | null;

  return (
    <div className="space-y-5 text-sm text-zinc-300">
      <Section title={`Components (${components.length})`}>
        {components.length === 0 ? (
          <div className="text-xs text-zinc-500">no components</div>
        ) : (
          <ul className="space-y-1">
            {components.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => onSelect({ kind: "component_instance", id: c.id })}
                  className="w-full rounded border border-zinc-800 bg-zinc-900/40 px-2 py-1.5 text-left transition-colors hover:bg-zinc-900"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-mono text-xs text-zinc-100">{c.id}</span>
                    <span className="text-[11px] text-zinc-500">{c.library_id}</span>
                  </div>
                  <div className="mt-0.5 truncate text-xs text-zinc-400">{c.label}</div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {requirements.length > 0 && (
        <Section title="Requirements">
          <ul className="space-y-1.5">
            {requirements.map((r, i) => (
              <li key={i} className="rounded border border-zinc-800 bg-zinc-900/40 px-2 py-1.5 text-xs">
                <div className="font-mono text-zinc-500">{String(r.kind ?? "")}</div>
                <div>{String(r.text ?? "")}</div>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {warnings.length > 0 && (
        <Section title="Warnings">
          <ul className="space-y-1.5">
            {warnings.map((w, i) => (
              <li
                key={i}
                className={`rounded border px-2 py-1.5 text-xs ${
                  w.level === "warn"
                    ? "border-amber-500/40 bg-amber-500/5 text-amber-200"
                    : w.level === "error"
                      ? "border-red-500/40 bg-red-500/10 text-red-200"
                      : "border-zinc-700 bg-zinc-900/40 text-zinc-300"
                }`}
              >
                <div className="font-mono">[{String(w.level)}] {String(w.code ?? "")}</div>
                <div className="mt-0.5">{String(w.text ?? "")}</div>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {fleet && (
        <Section title="Fleet">
          <KV k="device_name" v={String(fleet.device_name ?? "")} />
          {Array.isArray(fleet.tags) && fleet.tags.length > 0 && (
            <KV k="tags" v={(fleet.tags as string[]).join(", ")} />
          )}
        </Section>
      )}
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
  instanceId, design, onParamChange,
}: {
  instanceId: string;
  design: Design | null;
  onParamChange: (componentInstanceId: string, paramKey: string, value: unknown) => void;
}) {
  const components = readComponents(design);
  const inst = components.find((c) => c.id === instanceId) as ComponentInstance | undefined;
  const comp = useFetched(() => (inst ? api.getComponent(inst.library_id) : Promise.resolve(null)), [inst?.library_id]);

  if (!inst) return <div className="text-xs text-zinc-500">Component not found in design.</div>;
  if (!comp) return <Loading />;

  const c = comp as Record<string, unknown>;
  const schema = (c.params_schema ?? {}) as Record<string, never>;

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
