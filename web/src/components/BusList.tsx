/**
 * Per-type bus editor. Renders one card per bus, with editable id and
 * pin slots that vary by bus type. Adding a bus opens a tiny picker
 * for the type; removing leaves any connection targeting the bus
 * dangling (the inspector's render warnings surface that).
 */
import { useEffect, useState } from "react";
import {
  type BusType,
  addBus,
  removeBus,
  renameBus,
  updateBus,
} from "../lib/design";
import type { CompatibilityWarning, Design } from "../types/api";

const ALL_BUS_TYPES: BusType[] = ["i2c", "spi", "uart", "i2s", "1wire"];

// Pin slots that live on the bus itself for each type. Per-component pins
// (SPI cs, I2S DOUT/DIN) are not bus-level state and aren't shown here.
const PIN_SLOTS_BY_TYPE: Record<BusType, string[]> = {
  i2c:   ["sda", "scl"],
  spi:   ["clk", "miso", "mosi"],
  uart:  ["tx", "rx"],
  i2s:   ["lrclk", "bclk"],
  "1wire": [],
};

export function BusList({
  design, gpioPins, defaultBuses, compatibilityWarnings, onChange,
}: {
  design: Design;
  /** Pin names from the current board's gpio_capabilities, used to populate
   *  the pin selector dropdowns. Empty when no board is loaded -- the
   *  fields fall back to free-text input. */
  gpioPins: string[];
  /** board.default_buses if any -- used when adding a fresh bus so I2C
   *  lands on the board's canonical SDA/SCL out of the box. */
  defaultBuses: Record<string, Record<string, string>>;
  /** Whole-design compat warnings; bus warnings carry the bus id in
   *  `component_id`, so the card filters down to its own. */
  compatibilityWarnings: CompatibilityWarning[];
  onChange: (updater: (d: Design) => Design) => void;
}) {
  const buses = ((design.buses as Array<Record<string, unknown>> | undefined) ?? []).map((b) => ({
    id: String(b.id),
    type: String(b.type) as BusType,
    raw: b,
  }));
  const allBusIds = new Set(buses.map((b) => b.id));

  const [pickedType, setPickedType] = useState<BusType>("i2c");

  return (
    <div className="space-y-2">
      {buses.length === 0 ? (
        <div className="text-xs text-zinc-500">No buses.</div>
      ) : (
        <ul className="space-y-2">
          {buses.map((b) => (
            <li key={b.id}>
              <BusCard
                bus={b.raw}
                type={b.type}
                gpioPins={gpioPins}
                warnings={compatibilityWarnings.filter((w) => w.component_id === b.id)}
                otherBusIds={new Set([...allBusIds].filter((x) => x !== b.id))}
                onRename={(newId) => onChange((d) => renameBus(d, b.id, newId))}
                onChange={(patch) => onChange((d) => updateBus(d, b.id, patch))}
                onRemove={() => onChange((d) => removeBus(d, b.id))}
              />
            </li>
          ))}
        </ul>
      )}

      <div className="flex items-center gap-2">
        <select
          value={pickedType}
          onChange={(e) => setPickedType(e.target.value as BusType)}
          className="rounded border border-zinc-800 bg-zinc-950 px-1.5 py-0.5 text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
        >
          {ALL_BUS_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <button
          onClick={() => onChange((d) => addBus(d, pickedType, defaultBuses[pickedType]))}
          className="rounded border border-zinc-800 px-2 py-0.5 text-xs text-zinc-300 hover:bg-zinc-900"
          title={`Add a ${pickedType} bus${defaultBuses[pickedType] ? " on the board's defaults" : ""}`}
        >
          + add bus
        </button>
      </div>
    </div>
  );
}

function BusCard({
  bus, type, gpioPins, warnings, otherBusIds, onRename, onChange, onRemove,
}: {
  bus: Record<string, unknown>;
  type: BusType;
  gpioPins: string[];
  warnings: CompatibilityWarning[];
  /** Ids of every other bus in the design; used to refuse a rename that
   *  would collide. */
  otherBusIds: Set<string>;
  onRename: (newId: string) => void;
  onChange: (patch: Partial<Record<string, unknown>>) => void;
  onRemove: () => void;
}) {
  const slots = PIN_SLOTS_BY_TYPE[type];
  const id = String(bus.id);
  const freq = bus.frequency_hz as number | undefined;
  const baud = bus.baud_rate as number | undefined;

  // Local draft id while the user is typing. We commit on blur or Enter
  // so an intermediate value like "i" or "" doesn't tear the connections
  // table apart. The effect below resyncs the draft when the canonical
  // id changes from outside (e.g., a render-driven design refresh).
  const [draftId, setDraftId] = useState(id);
  useEffect(() => { setDraftId(id); }, [id]);

  function commitRename() {
    const next = draftId.trim();
    if (next === "" || next === id || otherBusIds.has(next)) {
      // Reject and revert -- the caller's onRename guards against the
      // collision case anyway, but we want to clear the visual drift.
      setDraftId(id);
      return;
    }
    onRename(next);
  }

  const draftDirty = draftId.trim() !== id;
  const draftCollides = otherBusIds.has(draftId.trim());

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/30 p-2">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <input
            type="text"
            value={draftId}
            onChange={(e) => setDraftId(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.currentTarget.blur();
              } else if (e.key === "Escape") {
                setDraftId(id);
                e.currentTarget.blur();
              }
            }}
            title={
              draftCollides
                ? `Another bus already uses '${draftId.trim()}'.`
                : "Press Enter or click away to apply. Esc to revert."
            }
            className={`w-28 rounded border bg-zinc-950 px-1.5 py-0.5 font-mono text-xs focus:outline-none ${
              draftCollides
                ? "border-red-500/50 text-red-200 focus:border-red-500"
                : draftDirty
                  ? "border-amber-500/50 text-amber-100 focus:border-amber-400"
                  : "border-zinc-800 text-zinc-100 focus:border-zinc-600"
            }`}
          />
          <span className="rounded border border-zinc-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400">
            {type}
          </span>
        </div>
        <button
          onClick={onRemove}
          title={`Remove ${id}`}
          className="rounded border border-zinc-800 px-1.5 py-0.5 text-xs text-zinc-500 transition-colors hover:border-red-500/40 hover:bg-red-500/10 hover:text-red-300"
        >
          ✕
        </button>
      </div>

      {slots.length === 0 ? (
        <div className="text-[11px] text-zinc-500">
          {type === "1wire"
            ? "1-wire pin lives on each component's connection target, not on the bus."
            : "no bus-level pins"}
        </div>
      ) : (
        <div className="grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-1">
          {slots.map((slot) => (
            <PinField
              key={slot}
              label={slot}
              value={(bus[slot] as string | undefined) ?? ""}
              gpioPins={gpioPins}
              onChange={(v) => onChange({ [slot]: v || undefined })}
            />
          ))}
        </div>
      )}

      {(type === "i2c" || type === "uart") && (
        <div className="mt-1.5 grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-1">
          <span className="w-16 text-[11px] text-zinc-500">
            {type === "uart" ? "baud" : "freq Hz"}
          </span>
          <input
            type="number"
            value={type === "uart" ? (baud ?? "") : (freq ?? "")}
            onChange={(e) => {
              const raw = e.target.value;
              const n = raw === "" ? undefined : parseInt(raw, 10);
              if (n !== undefined && Number.isNaN(n)) return;
              onChange(type === "uart" ? { baud_rate: n } : { frequency_hz: n });
            }}
            placeholder={type === "uart" ? "9600" : "100000"}
            className="w-32 rounded border border-zinc-800 bg-zinc-950 px-1.5 py-0.5 text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
          />
        </div>
      )}

      {warnings.length > 0 && (
        <ul className="mt-1.5 space-y-0.5">
          {warnings.map((w, i) => (
            <li
              key={`${w.code}:${w.pin_role}:${i}`}
              className={`rounded px-1.5 py-1 text-[10px] leading-snug ${
                w.severity === "error"
                  ? "border border-red-700/50 bg-red-900/20 text-red-200"
                  : w.severity === "warn"
                    ? "border border-amber-700/40 bg-amber-900/15 text-amber-200"
                    : "border border-zinc-700/50 bg-zinc-900/40 text-zinc-300"
              }`}
              title={w.code}
            >
              <span className="font-mono">{w.pin_role}@{w.pin}</span> · {w.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PinField({
  label, value, gpioPins, onChange,
}: {
  label: string;
  value: string;
  gpioPins: string[];
  onChange: (v: string) => void;
}) {
  const inOptions = gpioPins.includes(value);
  return (
    <>
      <span className="text-[11px] uppercase tracking-wide text-zinc-500">{label}</span>
      {gpioPins.length > 0 ? (
        <select
          value={inOptions ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          className="rounded border border-zinc-800 bg-zinc-950 px-1.5 py-0.5 text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
        >
          <option value="">(unset{!inOptions && value ? `: ${value}` : ""})</option>
          {gpioPins.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="rounded border border-zinc-800 bg-zinc-950 px-1.5 py-0.5 text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
        />
      )}
    </>
  );
}
