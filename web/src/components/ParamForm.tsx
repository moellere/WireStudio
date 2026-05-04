/**
 * Form generated from a component's `params_schema`. v1 supports the
 * scalar param types (string, integer, number, boolean) plus enums.
 *
 * Object/array params (filters, on_press, etc.) fall through to a
 * read-only JSON view -- editing those needs a richer UI that can wait.
 */

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
    return <div className="text-xs text-zinc-500">No editable params.</div>;
  }

  return (
    <div className="space-y-3">
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
  const labelEl = (
    <div className="flex items-baseline justify-between gap-2">
      <label htmlFor={`param-${k}`} className="font-mono text-xs text-zinc-200">{k}</label>
      {entry.default !== undefined && (
        <span className="text-[11px] text-zinc-500">default: {JSON.stringify(entry.default)}</span>
      )}
    </div>
  );

  return (
    <div>
      {labelEl}
      <div className="mt-1">{renderControl(k, entry, current, onChange)}</div>
      {entry.description && (
        <div className="mt-1 text-[11px] text-zinc-500">{entry.description}</div>
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
      <select
        id={id}
        value={v}
        onChange={(e) => onChange(k, coerceToType(e.target.value, entry.type))}
        className="w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
      >
        {entry.enum.map((opt) => (
          <option key={String(opt)} value={String(opt)}>{String(opt)}</option>
        ))}
      </select>
    );
  }

  if (entry.type === "boolean") {
    return (
      <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-zinc-300">
        <input
          id={id}
          type="checkbox"
          checked={Boolean(current)}
          onChange={(e) => onChange(k, e.target.checked)}
          className="h-4 w-4 cursor-pointer"
        />
        <span>{Boolean(current) ? "true" : "false"}</span>
      </label>
    );
  }

  if (entry.type === "integer" || entry.type === "number") {
    return (
      <input
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
        className="w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
      />
    );
  }

  if (entry.type === "object" || entry.type === "array") {
    return (
      <pre className="overflow-auto rounded border border-zinc-800 bg-zinc-950 p-2 text-[11px] text-zinc-400">
        {JSON.stringify(current, null, 2)}
        <div className="mt-2 italic text-zinc-500">structured editing not yet supported</div>
      </pre>
    );
  }

  // Default: string.
  return (
    <input
      id={id}
      type="text"
      value={current === undefined || current === null ? "" : String(current)}
      onChange={(e) => onChange(k, e.target.value)}
      className="w-full rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
    />
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
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="font-mono text-xs text-zinc-200">{k}</span>
        <span className="text-[11px] text-zinc-500">not in schema</span>
      </div>
      <pre className="mt-1 overflow-auto rounded border border-zinc-800 bg-zinc-950 p-2 text-[11px] text-zinc-400">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}
