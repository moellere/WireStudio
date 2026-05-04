/**
 * Connection editor: one row per connection of the selected component
 * instance. The row's first dropdown picks the target kind
 * (rail / gpio / bus / expander_pin); the rest of the row is the
 * kind-specific selector(s). Each change emits an immutable replacement
 * target up to the App via onChange(index, target).
 */

import type { ComponentSummary } from "../types/api";
import {
  type ConnectionRow,
  type ConnectionTarget,
  readBuses,
  readComponents,
} from "../lib/design";
import type { Design } from "../types/api";

type Kind = ConnectionTarget["kind"];
const KINDS: Kind[] = ["rail", "gpio", "bus", "expander_pin"];

interface Props {
  rows: ConnectionRow[];
  design: Design;
  boardData: unknown;
  libraryComponents: ComponentSummary[] | null;
  onChange: (connectionIndex: number, target: ConnectionTarget) => void;
}

export function ConnectionForm({
  rows, design, boardData, libraryComponents, onChange,
}: Props) {
  if (rows.length === 0) {
    return <div className="text-xs text-zinc-500">No connections.</div>;
  }
  const board = (boardData ?? {}) as Record<string, unknown>;
  const railNames = Array.isArray(board.rails)
    ? (board.rails as Array<Record<string, unknown>>).map((r) => String(r.name))
    : [];
  const gpioPins = Object.keys((board.gpio_capabilities ?? {}) as Record<string, unknown>);
  const buses = readBuses(design);
  const expanders = expandersFromDesign(design, libraryComponents);

  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <Row
          key={row.index}
          row={row}
          railNames={railNames}
          gpioPins={gpioPins}
          buses={buses}
          expanders={expanders}
          onChange={(t) => onChange(row.index, t)}
        />
      ))}
    </div>
  );
}

function Row({
  row, railNames, gpioPins, buses, expanders, onChange,
}: {
  row: ConnectionRow;
  railNames: string[];
  gpioPins: string[];
  buses: { id: string; type: string }[];
  expanders: { id: string; library_id: string }[];
  onChange: (t: ConnectionTarget) => void;
}) {
  const t = row.target;

  const onKindChange = (k: Kind) => {
    if (k === t.kind) return;
    onChange(defaultTargetForKind(k, { railNames, gpioPins, buses, expanders }));
  };

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/30 p-2">
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="font-mono text-xs text-zinc-100">{row.pin_role}</span>
        <select
          value={t.kind}
          onChange={(e) => onKindChange(e.target.value as Kind)}
          className="rounded border border-zinc-800 bg-zinc-950 px-1.5 py-0.5 text-[11px] text-zinc-200 focus:border-zinc-600 focus:outline-none"
        >
          {KINDS.map((k) => (
            <option key={k} value={k}>{k}</option>
          ))}
        </select>
      </div>

      {t.kind === "rail" && (
        <SelectInput
          label="rail"
          value={t.rail}
          options={railNames}
          onChange={(v) => onChange({ kind: "rail", rail: v })}
        />
      )}

      {t.kind === "gpio" && (
        <SelectInput
          label="pin"
          value={t.pin}
          options={gpioPins}
          allowFree
          onChange={(v) => onChange({ kind: "gpio", pin: v })}
        />
      )}

      {t.kind === "bus" && (
        <SelectInput
          label="bus"
          value={t.bus_id}
          options={buses.map((b) => b.id)}
          renderLabel={(id) => {
            const b = buses.find((x) => x.id === id);
            return b ? `${b.id} (${b.type})` : id;
          }}
          onChange={(v) => onChange({ kind: "bus", bus_id: v })}
        />
      )}

      {t.kind === "expander_pin" && (
        <ExpanderControls
          target={t}
          expanders={expanders}
          onChange={onChange}
        />
      )}
    </div>
  );
}

function ExpanderControls({
  target, expanders, onChange,
}: {
  target: Extract<ConnectionTarget, { kind: "expander_pin" }>;
  expanders: { id: string; library_id: string }[];
  onChange: (t: ConnectionTarget) => void;
}) {
  return (
    <div className="space-y-1.5">
      <SelectInput
        label="expander"
        value={target.expander_id}
        options={expanders.map((e) => e.id)}
        renderLabel={(id) => {
          const e = expanders.find((x) => x.id === id);
          return e ? `${e.id} (${e.library_id})` : id;
        }}
        onChange={(v) => onChange({ ...target, expander_id: v })}
      />
      <div className="flex items-center gap-2">
        <span className="w-16 text-[11px] text-zinc-500">number</span>
        <input
          type="number"
          min={0}
          value={target.number}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10);
            if (Number.isNaN(n)) return;
            onChange({ ...target, number: n });
          }}
          className="w-20 rounded border border-zinc-800 bg-zinc-950 px-1.5 py-0.5 text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
        />
      </div>
      <div className="flex items-center gap-2">
        <span className="w-16 text-[11px] text-zinc-500">mode</span>
        <select
          value={target.mode ?? ""}
          onChange={(e) => onChange({ ...target, mode: e.target.value || undefined })}
          className="flex-1 rounded border border-zinc-800 bg-zinc-950 px-1.5 py-0.5 text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
        >
          <option value="">(unset)</option>
          {["INPUT", "INPUT_PULLUP", "INPUT_PULLDOWN", "OUTPUT", "OUTPUT_OPEN_DRAIN"].map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>
      <div className="flex items-center gap-2">
        <span className="w-16 text-[11px] text-zinc-500">inverted</span>
        <input
          type="checkbox"
          checked={Boolean(target.inverted)}
          onChange={(e) => onChange({ ...target, inverted: e.target.checked })}
          className="h-3.5 w-3.5 cursor-pointer"
        />
      </div>
    </div>
  );
}

function SelectInput({
  label, value, options, onChange, allowFree = false, renderLabel,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  allowFree?: boolean;
  renderLabel?: (opt: string) => string;
}) {
  const inOptions = options.includes(value);
  return (
    <div className="flex items-center gap-2">
      <span className="w-16 text-[11px] text-zinc-500">{label}</span>
      {options.length > 0 ? (
        <select
          value={inOptions ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          className="flex-1 rounded border border-zinc-800 bg-zinc-950 px-1.5 py-0.5 text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
        >
          {!inOptions && (
            <option value="" disabled>(invalid: {value || "<unset>"})</option>
          )}
          {options.map((o) => (
            <option key={o} value={o}>{renderLabel ? renderLabel(o) : o}</option>
          ))}
        </select>
      ) : (
        <input
          type="text"
          value={value}
          readOnly={!allowFree}
          onChange={(e) => allowFree && onChange(e.target.value)}
          className="flex-1 rounded border border-zinc-800 bg-zinc-950 px-1.5 py-0.5 text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
        />
      )}
    </div>
  );
}

function expandersFromDesign(d: Design, libraryComponents: ComponentSummary[] | null) {
  if (!libraryComponents) return [];
  const expanderLibIds = new Set(
    libraryComponents.filter((c) => c.category === "io_expander").map((c) => c.id),
  );
  return readComponents(d).filter((c) => expanderLibIds.has(c.library_id));
}

function defaultTargetForKind(
  k: Kind,
  ctx: {
    railNames: string[];
    gpioPins: string[];
    buses: { id: string; type: string }[];
    expanders: { id: string; library_id: string }[];
  },
): ConnectionTarget {
  switch (k) {
    case "rail":
      return { kind: "rail", rail: ctx.railNames[0] ?? "GND" };
    case "gpio":
      return { kind: "gpio", pin: ctx.gpioPins[0] ?? "" };
    case "bus":
      return { kind: "bus", bus_id: ctx.buses[0]?.id ?? "" };
    case "expander_pin":
      return {
        kind: "expander_pin",
        expander_id: ctx.expanders[0]?.id ?? "",
        number: 0,
        mode: "INPUT_PULLUP",
        inverted: false,
      };
  }
}
