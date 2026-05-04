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
  return (d.connections as Array<Record<string, unknown>>)
    .map((c, index) => ({
      index,
      component_id: String(c.component_id),
      pin_role: String(c.pin_role),
      target: c.target as ConnectionTarget,
    }))
    .filter((c) => !componentId || c.component_id === componentId);
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
