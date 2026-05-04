import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Design } from "../types/api";

export type Selection =
  | { kind: "design" }
  | { kind: "board"; id: string }
  | { kind: "component"; id: string };

export function Inspector({ selection, design }: { selection: Selection; design: Design | null }) {
  return (
    <aside className="flex min-h-0 flex-col border-l border-zinc-800">
      <div className="border-b border-zinc-800 px-4 py-3">
        <div className="text-xs uppercase tracking-wide text-zinc-500">Inspector</div>
        <div className="mt-1 text-sm text-zinc-300">
          {selection.kind === "design" && "Design"}
          {selection.kind === "board" && <>Board · <code className="text-zinc-100">{selection.id}</code></>}
          {selection.kind === "component" && <>Component · <code className="text-zinc-100">{selection.id}</code></>}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4 text-sm">
        {selection.kind === "design" && <DesignInspector design={design} />}
        {selection.kind === "board" && <BoardInspector id={selection.id} />}
        {selection.kind === "component" && <ComponentInspector id={selection.id} />}
      </div>
    </aside>
  );
}

function DesignInspector({ design }: { design: Design | null }) {
  if (!design) return <div className="text-xs text-zinc-500">No design loaded.</div>;
  const requirements = Array.isArray(design.requirements) ? design.requirements as Array<Record<string, unknown>> : [];
  const warnings = Array.isArray(design.warnings) ? design.warnings as Array<Record<string, unknown>> : [];
  const fleet = (design.fleet ?? null) as Record<string, unknown> | null;

  return (
    <div className="space-y-5 text-sm text-zinc-300">
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
      <div className="text-xs text-zinc-500">
        Editing forms (params, connections, board picker) come next — for v1 the inspector is read-only.
      </div>
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

function ComponentInspector({ id }: { id: string }) {
  const comp = useFetched(() => api.getComponent(id), [id]);
  if (!comp) return <Loading />;
  const c = comp as Record<string, unknown>;
  const electrical = (c.electrical ?? {}) as Record<string, unknown>;
  const pins = Array.isArray(electrical.pins) ? electrical.pins as Array<Record<string, unknown>> : [];
  const esphome = (c.esphome ?? {}) as Record<string, unknown>;
  const required = Array.isArray(esphome.required_components) ? esphome.required_components as string[] : [];
  return (
    <div className="space-y-4">
      <div>
        <div className="text-base font-semibold text-zinc-100">{String(c.name)}</div>
        <div className="text-xs text-zinc-500">{String(c.category)}</div>
      </div>
      <Section title="Electrical">
        {electrical.vcc_min != null && (
          <KV k="VCC" v={`${electrical.vcc_min} – ${electrical.vcc_max}V`} />
        )}
        {electrical.current_ma_typical != null && (
          <KV k="current" v={`${electrical.current_ma_typical} typ / ${electrical.current_ma_peak} peak mA`} />
        )}
      </Section>
      {pins.length > 0 && (
        <Section title="Pins">
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
        </Section>
      )}
      {required.length > 0 && (
        <Section title="Required ESPHome components">
          <div className="font-mono text-xs">{required.join(", ")}</div>
        </Section>
      )}
      {Boolean(c.notes) && (
        <Section title="Notes">
          <p className="text-xs text-zinc-400">{String(c.notes)}</p>
        </Section>
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
