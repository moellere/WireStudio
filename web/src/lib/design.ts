import type { Design } from "../types/api";

export interface ComponentInstance {
  id: string;
  library_id: string;
  label: string;
  role?: string;
  params?: Record<string, unknown>;
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
