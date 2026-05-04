import type { Design } from "../types/api";

export interface ComponentInstance {
  id: string;
  library_id: string;
  label: string;
  role?: string;
  params?: Record<string, unknown>;
}

export type ConnectionTarget =
  | { kind: "rail"; rail: string }
  | { kind: "gpio"; pin: string }
  | { kind: "bus"; bus_id: string }
  | {
      kind: "expander_pin";
      expander_id: string;
      number: number;
      mode?: string;
      inverted?: boolean;
    };

export interface ConnectionRow {
  index: number;       // index into design.connections, for stable identity
  component_id: string;
  pin_role: string;
  target: ConnectionTarget;
  /** The pin name from `components[i].locked_pins[role]` if the user has
   *  locked this role; null otherwise. Read-only -- the inspector mutates
   *  the lock via setLockedPin, not by editing this field. */
  locked_pin: string | null;
}

export function readComponents(d: Design | null): ComponentInstance[] {
  if (!d || !Array.isArray(d.components)) return [];
  return (d.components as Array<Record<string, unknown>>).map((c) => ({
    id: String(c.id),
    library_id: String(c.library_id),
    label: String(c.label),
    role: c.role ? String(c.role) : undefined,
    params: (c.params as Record<string, unknown> | undefined) ?? undefined,
  }));
}

/**
 * Return a new design with `params[paramKey]` of the named component instance
 * set to `value`. Passing `undefined` deletes the key. Pure: never mutates `d`.
 */
export function updateComponentParam(
  d: Design,
  componentInstanceId: string,
  paramKey: string,
  value: unknown,
): Design {
  const components = (d.components as Array<Record<string, unknown>> | undefined) ?? [];
  const next = components.map((c) => {
    if (c.id !== componentInstanceId) return c;
    const params = { ...((c.params as Record<string, unknown> | undefined) ?? {}) };
    if (value === undefined) {
      delete params[paramKey];
    } else {
      params[paramKey] = value;
    }
    return { ...c, params };
  });
  return { ...d, components: next };
}

export function isDirty(original: Design | null, current: Design | null): boolean {
  if (!original || !current) return false;
  // Designs are JSON-shaped; stringify is fine at the scale we have.
  return JSON.stringify(original) !== JSON.stringify(current);
}

export function readConnections(d: Design | null, componentId?: string): ConnectionRow[] {
  if (!d || !Array.isArray(d.connections)) return [];
  const components = (d.components as Array<Record<string, unknown>> | undefined) ?? [];
  const locksByCid = new Map<string, Record<string, string>>();
  for (const c of components) {
    const lp = c.locked_pins as Record<string, string> | undefined;
    if (lp && typeof lp === "object") {
      locksByCid.set(String(c.id), lp);
    }
  }
  return (d.connections as Array<Record<string, unknown>>)
    .map((c, index) => {
      const cid = String(c.component_id);
      const role = String(c.pin_role);
      const locks = locksByCid.get(cid);
      return {
        index,
        component_id: cid,
        pin_role: role,
        target: c.target as ConnectionTarget,
        locked_pin: locks && typeof locks[role] === "string" ? locks[role] : null,
      };
    })
    .filter((c) => !componentId || c.component_id === componentId);
}

/**
 * Set or clear a single (componentId, pinRole) entry in a component's
 * `locked_pins` map. Passing `null` removes the entry; if the resulting
 * map is empty the field itself is dropped to keep the JSON tidy.
 * Pure: never mutates `d`.
 */
export function setLockedPin(
  d: Design,
  componentId: string,
  pinRole: string,
  pin: string | null,
): Design {
  const components = (d.components as Array<Record<string, unknown>> | undefined) ?? [];
  return {
    ...d,
    components: components.map((c) => {
      if (c.id !== componentId) return c;
      const existing = (c.locked_pins as Record<string, string> | undefined) ?? {};
      const next: Record<string, string> = { ...existing };
      if (pin === null || pin === "") {
        delete next[pinRole];
      } else {
        next[pinRole] = pin;
      }
      const { locked_pins: _drop, ...rest } = c;
      return Object.keys(next).length > 0
        ? { ...rest, locked_pins: next }
        : rest;
    }),
  };
}

/**
 * Replace the target of a single connection identified by its index in
 * `design.connections`. Pure: never mutates `d`.
 */
export function updateConnectionTarget(
  d: Design,
  index: number,
  target: ConnectionTarget,
): Design {
  const connections = (d.connections as Array<Record<string, unknown>> | undefined) ?? [];
  const next = connections.map((c, i) => (i === index ? { ...c, target } : c));
  return { ...d, connections: next };
}

export interface BusSummary {
  id: string;
  type: string;
}

export function readBuses(d: Design | null): BusSummary[] {
  if (!d || !Array.isArray(d.buses)) return [];
  return (d.buses as Array<Record<string, unknown>>).map((b) => ({
    id: String(b.id),
    type: String(b.type),
  }));
}

export interface Requirement {
  id: string;
  kind: "capability" | "environment" | "constraint";
  text: string;
}

export function readRequirements(d: Design | null): Requirement[] {
  if (!d || !Array.isArray(d.requirements)) return [];
  return (d.requirements as Array<Record<string, unknown>>).map((r) => ({
    id: String(r.id ?? ""),
    kind: (r.kind as Requirement["kind"]) ?? "capability",
    text: String(r.text ?? ""),
  }));
}

export function updateRequirement(d: Design, index: number, patch: Partial<Requirement>): Design {
  const reqs = (d.requirements as Array<Record<string, unknown>> | undefined) ?? [];
  const next = reqs.map((r, i) => (i === index ? { ...r, ...patch } : r));
  return { ...d, requirements: next };
}

export function addRequirement(d: Design): Design {
  const reqs = (d.requirements as Array<Record<string, unknown>> | undefined) ?? [];
  // Auto-generate an id like r1, r2, ... that isn't already used.
  const used = new Set(reqs.map((r) => String(r.id)));
  let n = reqs.length + 1;
  while (used.has(`r${n}`)) n += 1;
  const fresh = { id: `r${n}`, kind: "capability", text: "" };
  return { ...d, requirements: [...reqs, fresh] };
}

export function removeRequirement(d: Design, index: number): Design {
  const reqs = (d.requirements as Array<Record<string, unknown>> | undefined) ?? [];
  return { ...d, requirements: reqs.filter((_, i) => i !== index) };
}

export interface DesignWarning {
  level: "info" | "warn" | "error";
  code: string;
  text: string;
}

export function readWarnings(d: Design | null): DesignWarning[] {
  if (!d || !Array.isArray(d.warnings)) return [];
  return (d.warnings as Array<Record<string, unknown>>).map((w) => ({
    level: (w.level as DesignWarning["level"]) ?? "info",
    code: String(w.code ?? ""),
    text: String(w.text ?? ""),
  }));
}

export function updateWarning(d: Design, index: number, patch: Partial<DesignWarning>): Design {
  const ws = (d.warnings as Array<Record<string, unknown>> | undefined) ?? [];
  const next = ws.map((w, i) => (i === index ? { ...w, ...patch } : w));
  return { ...d, warnings: next };
}

export function addWarning(d: Design): Design {
  const ws = (d.warnings as Array<Record<string, unknown>> | undefined) ?? [];
  const fresh = { level: "info", code: "", text: "" };
  return { ...d, warnings: [...ws, fresh] };
}

export function removeWarning(d: Design, index: number): Design {
  const ws = (d.warnings as Array<Record<string, unknown>> | undefined) ?? [];
  return { ...d, warnings: ws.filter((_, i) => i !== index) };
}

export function setBoardLibraryId(d: Design, libraryId: string, mcu: string): Design {
  const board = (d.board as Record<string, unknown> | undefined) ?? {};
  return { ...d, board: { ...board, library_id: libraryId, mcu } };
}

export function setFleetField(d: Design, key: string, value: unknown): Design {
  const fleet = (d.fleet as Record<string, unknown> | undefined) ?? {};
  return { ...d, fleet: { ...fleet, [key]: value } };
}

// ---------------------------------------------------------------------------
// add / remove component
// ---------------------------------------------------------------------------

/** Library shape we read from /library/components/{id}. Just the bits used here. */
export interface LibraryComponentDetail {
  id: string;
  name: string;
  category?: string;
  electrical?: {
    vcc_min?: number | null;
    vcc_max?: number | null;
    pins?: Array<{
      role: string;
      kind: string;
      voltage?: number | null;
    }>;
  };
}

/** Optional context the add helper consults to wire up sensible defaults. */
export interface BoardContext {
  rails?: Array<{ name: string; voltage: number }>;
  default_buses?: Record<string, Record<string, string>>;
}

export interface AddComponentOptions {
  label?: string;
  /** Existing buses in the design (so SDA/SCL/SCK/etc. can default to one). */
  buses?: BusSummary[];
  /** Board rails so VCC/GND can pick a matching rail. */
  board?: BoardContext;
  /** Override the auto-generated instance id. */
  instanceIdHint?: string;
}

/** Generate a unique component id derived from the library id. */
export function nextInstanceId(d: Design, libraryId: string, hint?: string): string {
  const used = new Set(readComponents(d).map((c) => c.id));
  const safeHint = hint?.replace(/[^a-zA-Z0-9_]/g, "_");
  if (safeHint && !used.has(safeHint)) return safeHint;
  const base = libraryId.replace(/[^a-z0-9]/gi, "_");
  for (let n = 1; n < 1000; n++) {
    const candidate = `${base}_${n}`;
    if (!used.has(candidate)) return candidate;
  }
  return `${base}_${Date.now()}`;
}

/**
 * For a given library pin, build the target most likely to be useful as a
 * starting point. Buses without a matching candidate fall through as
 * `kind: bus, bus_id: ""` so the form shows them as `(invalid)` rather than
 * silently disappearing.
 */
function defaultTargetForPin(
  pin: { role: string; kind: string; voltage?: number | null },
  ctx: { rails: Array<{ name: string; voltage: number }>; buses: BusSummary[]; vccMin?: number | null; vccMax?: number | null },
): ConnectionTarget {
  const k = pin.kind;

  if (k === "power") {
    // Pick the lowest-voltage rail that satisfies the part's [vcc_min, vcc_max].
    const candidates = ctx.rails.filter((r) =>
      (ctx.vccMin == null || r.voltage >= ctx.vccMin) && (ctx.vccMax == null || r.voltage <= ctx.vccMax),
    );
    const chosen = candidates.sort((a, b) => a.voltage - b.voltage)[0]
      ?? ctx.rails.find((r) => r.name === "3V3")
      ?? ctx.rails.find((r) => r.voltage > 0)
      ?? ctx.rails[0];
    return { kind: "rail", rail: chosen?.name ?? "3V3" };
  }
  if (k === "ground") {
    const gnd = ctx.rails.find((r) => r.voltage === 0)?.name
      ?? ctx.rails.find((r) => /gnd/i.test(r.name))?.name
      ?? "GND";
    return { kind: "rail", rail: gnd };
  }

  const busKindToType: Record<string, string> = {
    i2c_sda: "i2c", i2c_scl: "i2c",
    spi_clk: "spi", spi_miso: "spi", spi_mosi: "spi",
    i2s_lrclk: "i2s", i2s_bclk: "i2s",
    uart_rx: "uart", uart_tx: "uart",
  };
  const wantBus = busKindToType[k];
  if (wantBus) {
    const bus = ctx.buses.find((b) => b.type === wantBus);
    return { kind: "bus", bus_id: bus?.id ?? "" };
  }

  // spi_cs and i2s_dout are per-component native GPIO, not part of the bus.
  // digital_in / digital_out / analog_in fall through to gpio placeholders.
  return { kind: "gpio", pin: "" };
}

/**
 * Bus types a library component requires, derived from its pin kinds.
 * Returns a set of types like `"i2c"`, `"spi"`, etc.
 */
export function neededBusTypes(lib: LibraryComponentDetail): Set<string> {
  const need = new Set<string>();
  for (const p of lib.electrical?.pins ?? []) {
    if (p.kind === "i2c_sda" || p.kind === "i2c_scl") need.add("i2c");
    else if (p.kind === "spi_clk" || p.kind === "spi_miso" || p.kind === "spi_mosi") need.add("spi");
    else if (p.kind === "i2s_lrclk" || p.kind === "i2s_bclk") need.add("i2s");
    else if (p.kind === "uart_rx" || p.kind === "uart_tx") need.add("uart");
  }
  return need;
}

/**
 * Ensure the design has a bus of every type the library component needs.
 * Missing buses are appended with the board's default pinout if available;
 * otherwise an empty bus skeleton is appended (the user will need to fill
 * in pins via the bus editor when that lands). Returns a new design.
 */
export function prepareBusesForLib(
  d: Design,
  lib: LibraryComponentDetail,
  board: BoardContext,
): Design {
  const need = neededBusTypes(lib);
  if (need.size === 0) return d;

  const existing = readBuses(d);
  const buses = (d.buses as Array<Record<string, unknown>> | undefined) ?? [];
  const additions: Array<Record<string, unknown>> = [];
  const defaults = board.default_buses ?? {};

  for (const t of need) {
    if (existing.some((b) => b.type === t)) continue;
    const id = nextBusId(d, additions, t);
    const def = defaults[t] ?? {};
    additions.push({ id, type: t, ...def });
  }

  if (additions.length === 0) return d;
  return { ...d, buses: [...buses, ...additions] };
}

function nextBusId(
  d: Design,
  pending: Array<Record<string, unknown>>,
  type: string,
): string {
  const used = new Set([
    ...readBuses(d).map((b) => b.id),
    ...pending.map((b) => String(b.id)),
  ]);
  for (let n = 0; n < 100; n++) {
    const id = `${type}${n}`;
    if (!used.has(id)) return id;
  }
  return `${type}_${Date.now()}`;
}

export type BusType = "i2c" | "spi" | "uart" | "i2s" | "1wire";

/** Add a bus of the given type; the new bus inherits the board's default
 * pinout when one is present, otherwise lands with empty pin slots and
 * relies on the user (or the pin solver) to fill them in. Pure. */
export function addBus(
  d: Design,
  type: BusType,
  defaults?: Record<string, string>,
): Design {
  const buses = (d.buses as Array<Record<string, unknown>> | undefined) ?? [];
  const id = nextBusId(d, [], type);
  const newBus: Record<string, unknown> = { id, type, ...(defaults ?? {}) };
  return { ...d, buses: [...buses, newBus] };
}

/** Patch a single bus by id. Pure: returns a new design.
 *
 *  NOTE: do NOT pass `id` in the patch -- a bus rename is more than a
 *  field write because every `connection.target.bus_id` referencing the
 *  old id has to follow. Use `renameBus` for that path; this helper
 *  silently strips an `id` key to keep the connection table from
 *  drifting out of sync. */
export function updateBus(
  d: Design,
  busId: string,
  patch: Partial<Record<string, unknown>>,
): Design {
  const buses = (d.buses as Array<Record<string, unknown>> | undefined) ?? [];
  const { id: _ignoredId, ...safePatch } = patch;
  return {
    ...d,
    buses: buses.map((b) => (b.id === busId ? { ...b, ...safePatch } : b)),
  };
}

/**
 * Rename a bus and rewrite every connection that targets it. Atomic:
 * the bus list and the connection table never diverge. No-op when
 * `oldId === newId`. If a bus with `newId` already exists we do
 * nothing -- the caller (a UI input on blur) is expected to validate
 * before calling, but the guard here keeps us out of the merge case
 * where two buses claim the same id.
 *
 * Pure: returns a new design.
 */
export function renameBus(d: Design, oldId: string, newId: string): Design {
  if (oldId === newId) return d;
  const buses = (d.buses as Array<Record<string, unknown>> | undefined) ?? [];
  if (!buses.some((b) => b.id === oldId)) return d;
  if (buses.some((b) => b.id === newId)) return d;
  const connections = (d.connections as Array<Record<string, unknown>> | undefined) ?? [];
  return {
    ...d,
    buses: buses.map((b) => (b.id === oldId ? { ...b, id: newId } : b)),
    connections: connections.map((c) => {
      const t = c.target as Record<string, unknown> | undefined;
      if (t && t.kind === "bus" && t.bus_id === oldId) {
        return { ...c, target: { ...t, bus_id: newId } };
      }
      return c;
    }),
  };
}

/** Remove a bus. Connections that target it are left in place; the
 *  inspector's bus-mismatch warning handles the dangling references. */
export function removeBus(d: Design, busId: string): Design {
  const buses = (d.buses as Array<Record<string, unknown>> | undefined) ?? [];
  return { ...d, buses: buses.filter((b) => b.id !== busId) };
}

/**
 * Append a fresh component instance plus auto-generated connections, one
 * per pin in the library entry. Pure: returns a new design.
 */
export function addComponent(
  d: Design,
  lib: LibraryComponentDetail,
  opts: AddComponentOptions = {},
): Design {
  const id = nextInstanceId(d, lib.id, opts.instanceIdHint);
  const components = (d.components as Array<Record<string, unknown>> | undefined) ?? [];
  const existingConnections = (d.connections as Array<Record<string, unknown>> | undefined) ?? [];

  const inst = {
    id,
    library_id: lib.id,
    label: opts.label ?? lib.name,
    params: {},
  };

  const pins = lib.electrical?.pins ?? [];
  const newConnections = pins.map((p) => ({
    component_id: id,
    pin_role: p.role,
    target: defaultTargetForPin(p, {
      rails: opts.board?.rails ?? [],
      buses: opts.buses ?? [],
      vccMin: lib.electrical?.vcc_min,
      vccMax: lib.electrical?.vcc_max,
    }),
  }));

  return {
    ...d,
    components: [...components, inst],
    connections: [...existingConnections, ...newConnections],
  };
}

/**
 * Remove the named component instance plus every connection that originates
 * from it. Connections that *target* it (via `expander_id`) are intentionally
 * left in place and become "(invalid)" in the form so the user can fix or
 * delete them deliberately.
 */
export function removeComponent(d: Design, instanceId: string): Design {
  const components = (d.components as Array<Record<string, unknown>> | undefined) ?? [];
  const connections = (d.connections as Array<Record<string, unknown>> | undefined) ?? [];
  return {
    ...d,
    components: components.filter((c) => c.id !== instanceId),
    connections: connections.filter((c) => c.component_id !== instanceId),
  };
}
