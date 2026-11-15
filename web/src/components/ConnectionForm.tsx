/**
 * Connection editor: one row per connection of the selected component
 * instance. The row's first dropdown picks the target kind
 * (rail / gpio / bus / expander_pin / component / net); the rest of the row is the
 * kind-specific selector(s). Each change emits an immutable replacement
 * target up to the App via onChange(index, target).
 */

import { useMemo } from "react";
import { Lock, LockOpen } from "lucide-react";
import type { ComponentSummary } from "../types/api";
import { Input, Select } from "./ui";
import {
  pinCaveat,
  readUsedPins,
  type ConnectionRow,
  type ConnectionTarget,
  readBuses,
  readComponents,
} from "../lib/design";
import type { Design } from "../types/api";

type Kind = ConnectionTarget["kind"];
const KINDS: Kind[] = ["rail", "gpio", "bus", "expander_pin", "component", "net"];

interface Props {
  rows: ConnectionRow[];
  design: Design;
  boardData: unknown;
  libraryComponents: ComponentSummary[] | null;
  onChange: (connectionIndex: number, target: ConnectionTarget) => void;
  onLockedPinChange: (componentId: string, pinRole: string, pin: string | null) => void;
}

export function ConnectionForm({
  rows, design, boardData, libraryComponents, onChange, onLockedPinChange,
}: Props) {
  const board = (boardData ?? {}) as Record<string, unknown>;

  const railNames = useMemo(() => {
    return Array.isArray(board.rails)
      ? (board.rails as Array<Record<string, unknown>>).map((r) => String(r.name))
      : [];
  }, [board.rails]);

  const gpioPins = useMemo(() => {
    return Object.keys((board.gpio_capabilities ?? {}) as Record<string, unknown>);
  }, [board.gpio_capabilities]);

  const gpioCaps = board.gpio_capabilities as Record<string, string[]> | undefined;
  const usedPins = useMemo(() => (design ? readUsedPins(design) : new Set<string>()), [design]);
  const pinLabel = (current: string) => (p: string) => {
    if (p === current) return p;
    if (usedPins.has(p)) return `${p} — in use`;
    const caveat = pinCaveat(gpioCaps?.[p] ?? []);
    return caveat ? `${p} — ${caveat}` : `${p} — safe`;
  };

  // ⚡ Bolt: Use single-pass loops to derive lookups directly, avoiding chained .map()/.filter() intermediate array allocations
  const { busIds, busDict } = useMemo(() => {
    const ids: string[] = [];
    const dict = new Map<string, string>();
    if (design) {
      for (const b of readBuses(design)) {
        ids.push(b.id);
        dict.set(b.id, `${b.id} (${b.type})`);
      }
    }
    return { busIds: ids, busDict: dict };
  }, [design]);

  const expanderLibIds = useMemo(() => {
    if (!libraryComponents) return new Set<string>();
    const ids = new Set<string>();
    for (const c of libraryComponents) {
      if (c.category === "io_expander") {
        ids.add(c.id);
      }
    }
    return ids;
  }, [libraryComponents]);

  // ⚡ Bolt: Derive expander and component IDs and Dictionaries in a single loop over components
  const { expanderIds, expanderDict, componentIds, componentDict } = useMemo(() => {
    const eIds: string[] = [];
    const eDict = new Map<string, string>();
    const cIds: string[] = [];
    const cDict = new Map<string, string>();

    if (design) {
      for (const c of readComponents(design)) {
        const label = `${c.id} (${c.library_id})`;

        cIds.push(c.id);
        cDict.set(c.id, label);

        if (expanderLibIds.has(c.library_id)) {
          eIds.push(c.id);
          eDict.set(c.id, label);
        }
      }
    }

    return {
      expanderIds: eIds, expanderDict: eDict,
      componentIds: cIds, componentDict: cDict,
    };
  }, [design, expanderLibIds]);

  // Roles each component has a connection for: the suggestions a `net`
  // target offers once a component is picked. A subcircuit's internal node
  // (`out_a`) is typed in; the list cannot know it without the library.
  const rolesByComponent = useMemo(() => {
    const m = new Map<string, string[]>();
    const conns = ((design as unknown as { connections?: unknown }).connections ?? []) as Array<{
      component_id: string; pin_role: string;
    }>;
    for (const c of conns) {
      const list = m.get(c.component_id) ?? [];
      if (!list.includes(c.pin_role)) list.push(c.pin_role);
      m.set(c.component_id, list);
    }
    return m;
  }, [design]);

  if (rows.length === 0) {
    return <div className="text-xs text-ink-faint">No connections.</div>;
  }

  return (
    <div className="space-y-1">
      {rows.map((row) => (
        <Row
          key={row.index}
          row={row}
          railNames={railNames}
          gpioPins={gpioPins}
          busIds={busIds}
          busDict={busDict}
          expanderIds={expanderIds}
          expanderDict={expanderDict}
          componentIds={componentIds}
          componentDict={componentDict}
          rolesByComponent={rolesByComponent}
          pinLabel={pinLabel}
          onChange={(t) => onChange(row.index, t)}
          onLockedPinChange={(pin) => onLockedPinChange(row.component_id, row.pin_role, pin)}
        />
      ))}
    </div>
  );
}

function Row({
  row, railNames, gpioPins, busIds, busDict, expanderIds, expanderDict, componentIds, componentDict,
  rolesByComponent, pinLabel, onChange, onLockedPinChange,
}: {
  pinLabel: (current: string) => (p: string) => string;
  row: ConnectionRow;
  railNames: string[];
  gpioPins: string[];
  busIds: string[];
  busDict: Map<string, string>;
  expanderIds: string[];
  expanderDict: Map<string, string>;
  componentIds: string[];
  componentDict: Map<string, string>;
  rolesByComponent: Map<string, string[]>;
  onChange: (t: ConnectionTarget) => void;
  onLockedPinChange: (pin: string | null) => void;
}) {
  const t = row.target;

  const onKindChange = (k: Kind) => {
    if (k === t.kind) return;
    onChange(defaultTargetForKind(k, { railNames, gpioPins, busIds, expanderIds, componentIds }));
  };

  // ⚡ Bolt: compute filtered hub options here once to avoid N allocations per render inside SelectInput map
  const availableComponentIds = useMemo(() => {
    return componentIds.filter((id) => id !== row.component_id);
  }, [componentIds, row.component_id]);

  return (
    <div>
      <div className="grid grid-cols-[4.75rem_4.25rem_minmax(0,1fr)_auto] items-center gap-1.5">
        <span className="truncate font-mono text-xs text-ink" title={row.pin_role}>{row.pin_role}</span>
        <Select
          aria-label={`${row.pin_role} kind`}
          value={t.kind}
          onChange={(e) => onKindChange(e.target.value as Kind)}
          className="w-full px-1"
        >
          {KINDS.map((k) => (
            <option key={k} value={k}>{k}</option>
          ))}
        </Select>

        {t.kind === "rail" && (
          <SelectInput
            label={`${row.pin_role} rail`}
            value={t.rail}
            options={railNames}
            onChange={(v) => onChange({ kind: "rail", rail: v })}
          />
        )}
        {t.kind === "gpio" && (
          <SelectInput
            label={`${row.pin_role} pin`}
            value={t.pin}
            options={gpioPins}
            allowFree
            renderLabel={pinLabel(t.pin)}
            onChange={(v) => onChange({ kind: "gpio", pin: v })}
          />
        )}
        {t.kind === "bus" && (
          <SelectInput
            label={`${row.pin_role} bus`}
            value={t.bus_id}
            options={busIds}
            renderLabel={(id) => busDict.get(id) || id}
            onChange={(v) => onChange({ kind: "bus", bus_id: v })}
          />
        )}
        {t.kind === "expander_pin" && (
          <SelectInput
            label={`${row.pin_role} expander`}
            value={t.expander_id}
            options={expanderIds}
            renderLabel={(id) => expanderDict.get(id) || id}
            onChange={(v) => onChange({ ...t, expander_id: v })}
          />
        )}
        {t.kind === "component" && (
          <SelectInput
            label={`${row.pin_role} hub`}
            value={t.component_id}
            options={availableComponentIds}
            renderLabel={(id) => componentDict.get(id) || id}
            onChange={(v) => onChange({ kind: "component", component_id: v })}
          />
        )}
        {t.kind === "net" && (
          <SelectInput
            label={`${row.pin_role} component`}
            value={t.component_id}
            options={availableComponentIds}
            renderLabel={(id) => componentDict.get(id) || id}
            onChange={(v) => onChange({ kind: "net", component_id: v, net: "" })}
          />
        )}

        {t.kind === "gpio" ? (
          <LockToggle
            role={row.pin_role}
            lockedPin={row.locked_pin}
            currentPin={t.pin}
            onLock={() => onLockedPinChange(t.pin || null)}
            onUnlock={() => onLockedPinChange(null)}
          />
        ) : (
          <span className="w-[26px]" />
        )}
      </div>

      {t.kind === "gpio" && row.locked_pin && row.locked_pin !== t.pin && (
        <div className="ml-[5.125rem] mt-1 rounded-md border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-200">
          locked to <code>{row.locked_pin}</code> but bound to <code>{t.pin || "<unset>"}</code>;
          solver will flag a mismatch.
        </div>
      )}
      {t.kind === "expander_pin" && (
        <div className="ml-[5.125rem] mt-1">
          <ExpanderControls target={t} onChange={onChange} />
        </div>
      )}
      {t.kind === "net" && (
        <div className="ml-[5.125rem] mt-1">
          <NetControls target={t} roles={rolesByComponent.get(t.component_id) ?? []} onChange={onChange} />
        </div>
      )}
    </div>
  );
}

/**
 * A passthrough connector position lands on a net another component owns:
 * one of its connected roles (listed) or, for a subcircuit component, an
 * internal node such as `out_a` (typed). Both fields empty leaves the
 * position unused.
 */
function NetControls({
  target, roles, onChange,
}: {
  target: Extract<ConnectionTarget, { kind: "net" }>;
  roles: string[];
  onChange: (t: ConnectionTarget) => void;
}) {
  const listId = `net-roles-${target.component_id || "none"}`;
  return (
    <div className="flex items-center gap-2">
      <span className="w-12 shrink-0 text-[11px] text-ink-faint">net</span>
      <Input
        compact
        mono
        aria-label="net"
        list={listId}
        value={target.net}
        placeholder="role or subcircuit node"
        onChange={(e) => onChange({ ...target, net: e.target.value })}
        className="flex-1"
      />
      <datalist id={listId}>
        {roles.map((r) => (
          <option key={r} value={r} />
        ))}
      </datalist>
    </div>
  );
}

/**
 * Per-row lock toggle. Three states:
 *  - locked & in sync: solid badge, click to unlock.
 *  - locked & diverged: amber-tinted badge showing the locked target;
 *                       click to unlock. (Re-locking from here would
 *                       overwrite the lock with whatever is currently
 *                       bound, which is rarely what the user wants.)
 *  - unlocked: outline button "lock"; click to write
 *              locked_pins[role] = currently bound pin.
 *
 * The solver's `locked_pin_mismatch` warning surfaces the diverged case
 * in the design pane; this control gives the user a one-click escape.
 */
function LockToggle({
  role, lockedPin, currentPin, onLock, onUnlock,
}: {
  role: string;
  lockedPin: string | null;
  currentPin: string;
  onLock: () => void;
  onUnlock: () => void;
}) {
  const base = "flex h-[26px] shrink-0 items-center justify-center gap-1 rounded-md border text-[10px] uppercase tracking-wider transition-colors";
  if (lockedPin === null) {
    return (
      <button
        type="button"
        onClick={onLock}
        disabled={!currentPin}
        aria-label={currentPin ? `lock ${role} to ${currentPin}` : `lock ${role}`}
        title={
          currentPin
            ? `Lock this role to ${currentPin}; the pin solver will not move it.`
            : "Pick a pin first, then lock it."
        }
        className={`${base} w-[26px] border-line text-ink-faint enabled:hover:border-line-strong enabled:hover:text-ink disabled:opacity-40`}
      >
        <LockOpen className="h-3.5 w-3.5" />
      </button>
    );
  }
  const diverged = lockedPin !== currentPin;
  return (
    <button
      type="button"
      onClick={onUnlock}
      aria-label={`${role} is locked to ${lockedPin}; unlock`}
      title={
        diverged
          ? `Locked to ${lockedPin} (bound: ${currentPin || "<unset>"}). Click to unlock.`
          : `Locked to ${lockedPin}. Click to unlock.`
      }
      className={`${base} ${
        diverged
          ? "border-amber-600/50 bg-amber-900/20 px-1.5 text-amber-200 hover:bg-amber-900/30"
          : "w-[26px] border-emerald-600/50 bg-emerald-900/20 text-emerald-200 hover:bg-emerald-900/30"
      }`}
    >
      <Lock className="h-3.5 w-3.5" />
      {diverged && <span className="font-mono normal-case">{lockedPin}</span>}
    </button>
  );
}

function ExpanderControls({
  target, onChange,
}: {
  target: Extract<ConnectionTarget, { kind: "expander_pin" }>;
  onChange: (t: ConnectionTarget) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-faint">
      <label className="flex items-center gap-1">
        number
        <Input
          compact
          type="number"
          min={0}
          value={target.number}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10);
            if (Number.isNaN(n)) return;
            onChange({ ...target, number: n });
          }}
          className="w-14"
        />
      </label>
      <label className="flex min-w-0 flex-1 items-center gap-1">
        mode
        <Select
          value={target.mode ?? ""}
          onChange={(e) => onChange({ ...target, mode: e.target.value || undefined })}
          className="min-w-0 flex-1"
        >
          <option value="">(unset)</option>
          {["INPUT", "INPUT_PULLUP", "INPUT_PULLDOWN", "OUTPUT", "OUTPUT_OPEN_DRAIN"].map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </Select>
      </label>
      <label className="flex cursor-pointer items-center gap-1">
        <input
          type="checkbox"
          checked={Boolean(target.inverted)}
          onChange={(e) => onChange({ ...target, inverted: e.target.checked })}
          className="h-3.5 w-3.5 cursor-pointer"
        />
        inverted
      </label>
    </div>
  );
}

function SelectInput({
  label, value, options, onChange, allowFree = false, renderLabel,
}: {
  /** Accessible name; the row's kind select already says what this is. */
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  allowFree?: boolean;
  renderLabel?: (opt: string) => string;
}) {
  const inOptions = options.includes(value);
  if (options.length === 0) {
    return (
      <Input
        compact
        mono
        type="text"
        aria-label={label}
        value={value}
        readOnly={!allowFree}
        onChange={(e) => allowFree && onChange(e.target.value)}
      />
    );
  }
  return (
    <Select mono aria-label={label} value={inOptions ? value : ""} onChange={(e) => onChange(e.target.value)}>
      {!inOptions && (
        <option value="" disabled>(invalid: {value || "<unset>"})</option>
      )}
      {options.map((o) => (
        <option key={o} value={o}>{renderLabel ? renderLabel(o) : o}</option>
      ))}
    </Select>
  );
}

function defaultTargetForKind(
  k: Kind,
  ctx: {
    railNames: string[];
    gpioPins: string[];
    busIds: string[];
    expanderIds: string[];
    componentIds: string[];
  },
): ConnectionTarget {
  switch (k) {
    case "rail":
      return { kind: "rail", rail: ctx.railNames[0] ?? "GND" };
    case "gpio":
      return { kind: "gpio", pin: ctx.gpioPins[0] ?? "" };
    case "bus":
      return { kind: "bus", bus_id: ctx.busIds[0] ?? "" };
    case "expander_pin":
      return {
        kind: "expander_pin",
        expander_id: ctx.expanderIds[0] ?? "",
        number: 0,
        mode: "INPUT_PULLUP",
        inverted: false,
      };
    case "component":
      return { kind: "component", component_id: ctx.componentIds[0] ?? "" };
    case "net":
      return { kind: "net", component_id: "", net: "" };
  }
}
