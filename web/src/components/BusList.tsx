/**
 * Per-type bus editor. Renders one card per bus, with editable id and
 * pin slots that vary by bus type. Adding a bus opens a tiny picker
 * for the type; removing leaves any connection targeting the bus
 * dangling (the inspector's render warnings surface that).
 */
import { useState } from "react";
import {
  type BusType,
  addBus,
  removeBus,
  updateBus,
} from "../lib/design";
import type { Design } from "../types/api";

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
  design, gpioPins, defaultBuses, onChange,
}: {
  design: Design;
  /** Pin names from the current board's gpio_capabilities, used to populate
   *  the pin selector dropdowns. Empty when no board is loaded -- the
   *  fields fall back to free-text input. */
  gpioPins: string[];
  /** board.default_buses if any -- used when adding a fresh bus so I2C
   *  lands on the board's canonical SDA/SCL out of the box. */
  defaultBuses: Record<string, Record<string, string>>;
  onChange: (updater: (d: Design) => Design) => void;
}) {
  const buses = ((design.buses as Array<Record<string, unknown>> | undefined) ?? []).map((b) => ({
    id: String(b.id),
    type: String(b.type) as BusType,
    raw: b,
  }));

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
  bus, type, gpioPins, onChange, onRemove,
}: {
  bus: Record<string, unknown>;
  type: BusType;
  gpioPins: string[];
  onChange: (patch: Partial<Record<string, unknown>>) => void;
  onRemove: () => void;
}) {
  const slots = PIN_SLOTS_BY_TYPE[type];
  const id = String(bus.id);
  const freq = bus.frequency_hz as number | undefined;
  const baud = bus.baud_rate as number | undefined;

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/30 p-2">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <input
            type="text"
            value={id}
            onChange={(e) => onChange({ id: e.target.value })}
            className="w-28 rounded border border-zinc-800 bg-zinc-950 px-1.5 py-0.5 font-mono text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
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
