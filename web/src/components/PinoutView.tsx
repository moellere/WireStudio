/**
 * Drag-and-drop pinout view for the component-instance inspector.
 *
 * Renders two columns side by side:
 *
 *   - Left: every GPIO pin on the current board, with capability badges
 *           (boot strap, ADC unit, input-only, serial console).
 *   - Right: every kind=gpio connection on the selected component
 *           instance, draggable.
 *
 * Drop a connection onto a board pin to rewrite the connection's
 * target to {kind: "gpio", pin: <pin>}. Conflicts (the destination
 * pin already used by a *different* component's connection) render
 * red but the drop is still allowed -- the user can then resolve via
 * the existing CSP solver or by hand. The form-based ConnectionForm
 * stays available alongside this view; the inspector toggles between
 * the two.
 */
import type { ComponentInstance, ConnectionRow, ConnectionTarget } from "../lib/design";

interface Props {
  rows: ConnectionRow[];                    // connections of the selected instance
  allConnections: ConnectionRow[];          // every connection in the design (for conflict detection)
  instance: ComponentInstance;
  gpioCapabilities: Record<string, string[]>;
  onChange: (connectionIndex: number, target: ConnectionTarget) => void;
}

const SPECIAL_BADGES: { tag: string; label: string; tone: string }[] = [
  { tag: "boot_high", label: "boot HIGH", tone: "border-amber-700/40 bg-amber-900/15 text-amber-200" },
  { tag: "boot_low",  label: "boot LOW",  tone: "border-amber-700/40 bg-amber-900/15 text-amber-200" },
  { tag: "input_only", label: "input only", tone: "border-rose-700/40 bg-rose-900/15 text-rose-200" },
  { tag: "serial_tx", label: "TX",        tone: "border-rose-700/40 bg-rose-900/15 text-rose-200" },
  { tag: "serial_rx", label: "RX",        tone: "border-rose-700/40 bg-rose-900/15 text-rose-200" },
  { tag: "adc1",      label: "ADC1",      tone: "border-emerald-700/40 bg-emerald-900/15 text-emerald-200" },
  { tag: "adc2",      label: "ADC2",      tone: "border-amber-700/40 bg-amber-900/15 text-amber-200" },
  { tag: "i2c_sda",   label: "SDA",       tone: "border-blue-700/40 bg-blue-900/15 text-blue-200" },
  { tag: "i2c_scl",   label: "SCL",       tone: "border-blue-700/40 bg-blue-900/15 text-blue-200" },
];

const DRAG_MIME = "application/x-esphome-studio-connection-index";

export function PinoutView({
  rows, allConnections, instance, gpioCapabilities, onChange,
}: Props) {
  const gpioConnections = rows.filter((r) => r.target.kind === "gpio");
  const otherUses: Map<string, string> = new Map();
  for (const c of allConnections) {
    if (c.component_id === instance.id) continue;
    if (c.target.kind === "gpio" && c.target.pin) {
      otherUses.set(c.target.pin, `${c.component_id}.${c.pin_role}`);
    }
  }
  // Pin -> the connection on THIS instance that targets it (for the
  // "currently here" annotation on each board row).
  const myUses: Map<string, string> = new Map();
  for (const c of gpioConnections) {
    if (c.target.kind === "gpio" && c.target.pin) {
      myUses.set(c.target.pin, c.pin_role);
    }
  }

  const pinNames = Object.keys(gpioCapabilities);

  function handleDrop(pin: string, e: React.DragEvent) {
    e.preventDefault();
    const raw = e.dataTransfer.getData(DRAG_MIME);
    if (!raw) return;
    const idx = parseInt(raw, 10);
    if (Number.isNaN(idx)) return;
    onChange(idx, { kind: "gpio", pin });
  }

  if (pinNames.length === 0) {
    return (
      <div className="text-xs text-zinc-500">
        No board pinout available -- pick a board first.
      </div>
    );
  }
  if (gpioConnections.length === 0) {
    return (
      <div className="text-xs text-zinc-500">
        This component has no gpio connections to drag. Use the Form view
        to set rail / bus / expander_pin / component targets.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3">
      {/* Left: board pins (drop targets). */}
      <div className="space-y-1">
        <div className="text-[11px] uppercase tracking-wide text-zinc-500">
          Board pins
        </div>
        <ul className="space-y-1">
          {pinNames.map((pin) => {
            const caps = gpioCapabilities[pin] ?? [];
            const occupiedBy = otherUses.get(pin);
            const heldHere = myUses.get(pin);
            return (
              <li key={pin}>
                <div
                  data-testid={`pin-${pin}`}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => handleDrop(pin, e)}
                  className={`flex items-center gap-2 rounded border px-2 py-1 text-xs transition-colors ${
                    occupiedBy
                      ? "border-rose-700/40 bg-rose-900/10 text-zinc-200"
                      : heldHere
                        ? "border-emerald-700/40 bg-emerald-900/15 text-zinc-100"
                        : "border-zinc-800 bg-zinc-900/30 text-zinc-200 hover:border-zinc-600"
                  }`}
                >
                  <span className="w-14 shrink-0 font-mono">{pin}</span>
                  <div className="flex flex-1 flex-wrap items-center gap-1">
                    {SPECIAL_BADGES.filter((b) => caps.includes(b.tag)).map((b) => (
                      <span
                        key={b.tag}
                        className={`rounded border px-1 text-[10px] uppercase tracking-wide ${b.tone}`}
                      >
                        {b.label}
                      </span>
                    ))}
                    {heldHere && (
                      <span className="ml-auto text-[10px] text-emerald-300">
                        ← {heldHere}
                      </span>
                    )}
                    {occupiedBy && !heldHere && (
                      <span className="ml-auto text-[10px] text-rose-300">
                        used by {occupiedBy}
                      </span>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      </div>

      {/* Right: this component's gpio connections (draggable). */}
      <div className="space-y-1">
        <div className="text-[11px] uppercase tracking-wide text-zinc-500">
          {instance.id} pins
        </div>
        <ul className="space-y-1">
          {gpioConnections.map((row) => {
            const t = row.target as { kind: "gpio"; pin: string };
            return (
              <li key={row.index}>
                <div
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData(DRAG_MIME, String(row.index));
                    e.dataTransfer.effectAllowed = "move";
                  }}
                  data-testid={`drag-${row.pin_role}`}
                  className="flex cursor-grab items-center justify-between gap-2 rounded border border-zinc-800 bg-zinc-900/40 px-2 py-1 text-xs hover:border-zinc-600 active:cursor-grabbing"
                >
                  <span className="font-mono">{row.pin_role}</span>
                  <span className={`font-mono ${t.pin ? "text-zinc-100" : "text-zinc-500"}`}>
                    {t.pin || "(unbound)"}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
        <p className="pt-1 text-[11px] text-zinc-500">
          Drag a row onto a board pin on the left to bind it. Red rows
          are already used by another component's connection.
        </p>
      </div>
    </div>
  );
}
