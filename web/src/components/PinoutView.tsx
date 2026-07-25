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
import { useMemo } from "react";
import type { ComponentInstance, ConnectionRow, ConnectionTarget } from "../lib/design";

interface Props {
  rows: ConnectionRow[];                    // connections of the selected instance
  allConnections: ConnectionRow[];          // every connection in the design (for conflict detection)
  instance: ComponentInstance;
  gpioCapabilities: Record<string, string[]>;
  onChange: (connectionIndex: number, target: ConnectionTarget) => void;
}

const SPECIAL_BADGES: { tag: string; label: string; tone: string }[] = [
  { tag: "boot_high", label: "boot HIGH", tone: "border-amber-500/30 bg-amber-500/10 text-amber-200" },
  { tag: "boot_low",  label: "boot LOW",  tone: "border-amber-500/30 bg-amber-500/10 text-amber-200" },
  { tag: "input_only", label: "input only", tone: "border-rose-500/30 bg-rose-500/10 text-rose-200" },
  { tag: "serial_tx", label: "TX",        tone: "border-rose-500/30 bg-rose-500/10 text-rose-200" },
  { tag: "serial_rx", label: "RX",        tone: "border-rose-500/30 bg-rose-500/10 text-rose-200" },
  { tag: "adc1",      label: "ADC1",      tone: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" },
  { tag: "adc2",      label: "ADC2",      tone: "border-amber-500/30 bg-amber-500/10 text-amber-200" },
  { tag: "i2c_sda",   label: "SDA",       tone: "border-accent-500/30 bg-accent-500/10 text-accent-200" },
  { tag: "i2c_scl",   label: "SCL",       tone: "border-accent-500/30 bg-accent-500/10 text-accent-200" },
];

const DRAG_MIME = "application/x-wirestudio-connection-index";

export function PinoutView({
  rows, allConnections, instance, gpioCapabilities, onChange,
}: Props) {
  const gpioConnections = useMemo(
    () => rows.filter((r) => r.target.kind === "gpio"),
    [rows]
  );

  const otherUses = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of allConnections) {
      if (c.component_id === instance.id) continue;
      if (c.target.kind === "gpio" && c.target.pin) {
        map.set(c.target.pin, `${c.component_id}.${c.pin_role}`);
      }
    }
    return map;
  }, [allConnections, instance.id]);

  // Pin -> the connection on THIS instance that targets it (for the
  // "currently here" annotation on each board row).
  const myUses = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of gpioConnections) {
      if (c.target.kind === "gpio" && c.target.pin) {
        map.set(c.target.pin, c.pin_role);
      }
    }
    return map;
  }, [gpioConnections]);

  const pinNames = useMemo(
    () => Object.keys(gpioCapabilities),
    [gpioCapabilities]
  );

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
      <div className="text-xs text-ink-faint">
        No board pinout available -- pick a board first.
      </div>
    );
  }
  if (gpioConnections.length === 0) {
    return (
      <div className="text-xs text-ink-faint">
        This component has no gpio connections to drag. Use the Form view
        to set rail / bus / expander_pin / component targets.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3">
      {/* Left: board pins (drop targets). */}
      <div className="space-y-1">
        <div className="text-[11px] uppercase tracking-wider text-ink-faint">
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
                  className={`flex items-center gap-2 rounded-md ring-1 px-2 py-1 text-xs transition-colors ${
                    occupiedBy
                      ? "bg-rose-500/10 text-ink ring-rose-500/30"
                      : heldHere
                        ? "bg-accent-500/10 text-accent-200 ring-accent-500/30"
                        : "bg-surface-2 text-ink ring-line hover:ring-line-strong"
                  }`}
                >
                  <span className="w-14 shrink-0 font-mono">{pin}</span>
                  <div className="flex flex-1 flex-wrap items-center gap-1">
                    {SPECIAL_BADGES.map((b) => caps.includes(b.tag) ? (
                      <span
                        key={b.tag}
                        className={`rounded-md border px-1 text-[10px] uppercase tracking-wider ${b.tone}`}
                      >
                        {b.label}
                      </span>
                    ) : null)}
                    {heldHere && (
                      <span className="ml-auto text-[10px] text-accent-300">
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
        <div className="text-[11px] uppercase tracking-wider text-ink-faint">
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
                  className="flex cursor-grab items-center justify-between gap-2 rounded-md border border-line bg-surface-2/40 px-2 py-1 text-xs hover:border-line-strong active:cursor-grabbing"
                >
                  <span className="font-mono">{row.pin_role}</span>
                  <span className={`font-mono ${t.pin ? "text-ink" : "text-ink-faint"}`}>
                    {t.pin || "(unbound)"}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
        <p className="pt-1 text-[11px] text-ink-faint">
          Drag a row onto a board pin on the left to bind it. Red rows
          are already used by another component's connection.
        </p>
      </div>
    </div>
  );
}
