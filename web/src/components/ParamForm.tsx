/**
 * Form generated from a component's `params_schema`. v1 supports the
 * scalar param types (string, integer, number, boolean) plus enums.
 *
 * Object/array params (filters, on_press, sensors, etc.) edit as a
 * JSON textarea -- structured per-key UI is component-specific so
 * the generic editor stays JSON-text-with-validation.
 */

import { useState } from "react";
import { Input, Select } from "./ui";

interface SchemaEntry {
  type?: "string" | "integer" | "number" | "boolean" | "object" | "array";
  enum?: Array<string | number>;
  default?: unknown;
  description?: string;
  minimum?: number;
  maximum?: number;
}

type Schema = Record<string, SchemaEntry>;

interface Props {
  schema: Schema;
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}

export function ParamForm({ schema, values, onChange }: Props) {
  // Show every schema entry plus any value that isn't covered by the schema.
  const schemaKeys = Object.keys(schema);
  const extraKeys = Object.keys(values ?? {}).filter((k) => !schemaKeys.includes(k));
  const allKeys = [...schemaKeys, ...extraKeys];

  if (allKeys.length === 0) {
    return <div className="text-xs text-ink-faint">No editable params.</div>;
  }

  return (
    <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
      {allKeys.map((key) => {
        const entry = schema[key];
        const current = values?.[key];
        if (!entry) {
          return <ExtraField key={key} k={key} value={current} />;
        }
        return (
          <ParamRow key={key} k={key} entry={entry} current={current} onChange={onChange} />
        );
      })}
    </div>
  );
}

function ParamRow({
  k, entry, current, onChange,
}: {
  k: string;
  entry: SchemaEntry;
  current: unknown;
  onChange: (key: string, value: unknown) => void;
}) {
  const defaultText = entry.default === undefined
    ? null
    : typeof entry.default === "string" ? entry.default : JSON.stringify(entry.default);
  const labelEl = (
    <div className="flex items-baseline justify-between gap-2">
      <label htmlFor={`param-${k}`} className="min-w-0 truncate font-mono text-xs text-ink" title={k}>{k}</label>
      {defaultText !== null && (
        <span className="max-w-[45%] shrink-0 truncate text-[11px] text-ink-faint" title={`default: ${defaultText}`}>
          {defaultText}
        </span>
      )}
    </div>
  );
  // Scalars sit two to a row; JSON editors need the full width.
  const wide = entry.type === "object" || entry.type === "array";

  return (
    <div className={wide ? "col-span-2" : "min-w-0"}>
      {labelEl}
      <div className="mt-1">{renderControl(k, entry, current, onChange)}</div>
      {entry.description && (
        <div className="mt-1 text-[11px] text-ink-faint">{entry.description}</div>
      )}
    </div>
  );
}

function renderControl(
  k: string,
  entry: SchemaEntry,
  current: unknown,
  onChange: (key: string, value: unknown) => void,
) {
  const id = `param-${k}`;
  if (entry.enum && entry.enum.length > 0) {
    const v = current !== undefined ? String(current) : "";
    return (
      <Select id={id} mono value={v} onChange={(e) => onChange(k, coerceToType(e.target.value, entry.type))}>
        {entry.enum.map((opt) => (
          <option key={String(opt)} value={String(opt)}>{String(opt)}</option>
        ))}
      </Select>
    );
  }

  if (entry.type === "boolean") {
    return (
      <label className="inline-flex h-[26px] cursor-pointer items-center gap-2 font-mono text-xs text-ink-dim">
        <input
          id={id}
          type="checkbox"
          checked={Boolean(current)}
          onChange={(e) => onChange(k, e.target.checked)}
          className="h-3.5 w-3.5 cursor-pointer"
        />
        <span>{current ? "true" : "false"}</span>
      </label>
    );
  }

  if (entry.type === "integer" || entry.type === "number") {
    return (
      <Input
        compact
        mono
        id={id}
        type="number"
        step={entry.type === "integer" ? 1 : "any"}
        min={entry.minimum}
        max={entry.maximum}
        value={current === undefined || current === null ? "" : String(current)}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") return onChange(k, undefined);
          const n = entry.type === "integer" ? parseInt(raw, 10) : parseFloat(raw);
          if (Number.isNaN(n)) return;
          onChange(k, n);
        }}
      />
    );
  }

  if (entry.type === "object" || entry.type === "array") {
    return (
      <StructuredParamEditor
        paramKey={k}
        value={current}
        kind={entry.type}
        onChange={onChange}
      />
    );
  }

  // Default: string.
  return (
    <Input
      compact
      mono
      id={id}
      type="text"
      value={current === undefined || current === null ? "" : String(current)}
      onChange={(e) => onChange(k, e.target.value)}
    />
  );
}

/**
 * JSON textarea for object/array params -- the generic editor used when a
 * component's params_schema declares a nested shape (e.g. uart_gps.sensors,
 * pulse_counter.filters). Keeps the in-progress text in local state so a
 * mid-edit (`{"a":1`) doesn't get clobbered as invalid JSON; only commits
 * to the design when the buffer parses cleanly.
 *
 * Tradeoff: it's "edit raw JSON", not a structured per-key UI. For
 * complex shapes (e.g. uart_gps sub-sensor toggles) a follow-up can add
 * a component-specific editor; this unblocks the general case today.
 */
function StructuredParamEditor({
  paramKey,
  value,
  kind,
  onChange,
}: {
  paramKey: string;
  value: unknown;
  kind: "object" | "array";
  onChange: (k: string, v: unknown) => void;
}) {
  const initial =
    value === undefined || value === null
      ? kind === "array" ? "[]" : "{}"
      : JSON.stringify(value, null, 2);
  const [text, setText] = useState(initial);
  const [error, setError] = useState<string | null>(null);

  // Local edit state is intentionally not synced from `value` on every
  // render: a mid-edit ('{"a":1') would get blown away by the parent's
  // re-render. The buffer initialises from `value` on mount; if the
  // parent design switches under the editor, the user re-selects the
  // component to remount the row. Rare enough for a spike-grade fix.

  function handleChange(next: string) {
    setText(next);
    if (next.trim() === "") {
      setError(null);
      onChange(paramKey, undefined);
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return;
    }
    const expectedArray = kind === "array";
    const isArray = Array.isArray(parsed);
    if (expectedArray && !isArray) {
      setError("expected a JSON array");
      return;
    }
    if (!expectedArray && (isArray || typeof parsed !== "object" || parsed === null)) {
      setError("expected a JSON object");
      return;
    }
    setError(null);
    onChange(paramKey, parsed);
  }

  return (
    <div className="space-y-1">
      <textarea
        value={text}
        onChange={(e) => handleChange(e.target.value)}
        spellCheck={false}
        rows={Math.min(12, Math.max(3, text.split("\n").length))}
        className={`w-full rounded-md border bg-surface-1 p-2 font-mono text-[11px] text-ink focus:outline-none ${
          error ? "border-rose-500/60" : "border-line focus:border-accent-500/60"
        }`}
      />
      {error && (
        <div className="text-[11px] text-rose-400">
          JSON parse error: {error}
        </div>
      )}
    </div>
  );
}

function coerceToType(s: string, t: SchemaEntry["type"]): unknown {
  if (t === "integer") {
    const n = parseInt(s, 10);
    return Number.isNaN(n) ? s : n;
  }
  if (t === "number") {
    const n = parseFloat(s);
    return Number.isNaN(n) ? s : n;
  }
  return s;
}

function ExtraField({ k, value }: { k: string; value: unknown }) {
  // A string shows as written (a lambda keeps its line breaks); anything else as JSON.
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const wide = text.length > 16 || text.includes("\n");
  return (
    <div className={wide ? "col-span-2" : "min-w-0"}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="min-w-0 truncate font-mono text-xs text-ink" title={k}>{k}</span>
        <span className="shrink-0 text-[11px] text-ink-faint">not in schema</span>
      </div>
      <pre
        className={`mt-1 rounded-md border border-line bg-surface-1 px-2 font-mono text-[11px] text-ink-dim ${
          wide ? "max-h-40 overflow-auto whitespace-pre-wrap break-words py-1.5 leading-4" : "h-[26px] overflow-hidden leading-[24px]"
        }`}
      >
        {text}
      </pre>
    </div>
  );
}
