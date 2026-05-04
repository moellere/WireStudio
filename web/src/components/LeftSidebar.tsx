import { useMemo, useState } from "react";
import type { BoardSummary, ComponentSummary, ExampleSummary, SavedDesignSummary } from "../types/api";

type Tab = "examples" | "saved" | "boards" | "components";

interface Props {
  examples: ExampleSummary[] | null;
  saved: SavedDesignSummary[] | null;
  boards: BoardSummary[] | null;
  components: ComponentSummary[] | null;
  selectedExample: string | null;
  selectedSaved: string | null;
  onSelectExample: (id: string) => void;
  onSelectSaved: (id: string) => void;
  onDeleteSaved: (id: string) => void;
  onSelectBoard: (id: string) => void;
  onSelectComponent: (id: string) => void;
}

export function LeftSidebar(props: Props) {
  const [tab, setTab] = useState<Tab>("examples");
  const [search, setSearch] = useState("");

  return (
    <aside className="flex min-h-0 flex-col border-r border-zinc-800">
      <div className="flex border-b border-zinc-800 text-xs">
        {(["examples", "saved", "boards", "components"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 px-2 py-2 capitalize transition-colors ${
              tab === t
                ? "bg-zinc-900 text-zinc-100"
                : "text-zinc-500 hover:bg-zinc-900/50 hover:text-zinc-300"
            }`}
          >
            {t}
            {t === "saved" && props.saved && props.saved.length > 0 && (
              <span className="ml-1 text-[10px] text-zinc-500">({props.saved.length})</span>
            )}
          </button>
        ))}
      </div>
      <input
        type="search"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder={`Filter ${tab}...`}
        className="m-2 rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {tab === "examples" && (
          <ExamplesList
            items={props.examples}
            search={search}
            selected={props.selectedExample}
            onSelect={props.onSelectExample}
          />
        )}
        {tab === "saved" && (
          <SavedList
            items={props.saved}
            search={search}
            selected={props.selectedSaved}
            onSelect={props.onSelectSaved}
            onDelete={props.onDeleteSaved}
          />
        )}
        {tab === "boards" && (
          <BoardsList items={props.boards} search={search} onSelect={props.onSelectBoard} />
        )}
        {tab === "components" && (
          <ComponentsList items={props.components} search={search} onSelect={props.onSelectComponent} />
        )}
      </div>
    </aside>
  );
}

function SavedList({
  items, search, selected, onSelect, onDelete,
}: {
  items: SavedDesignSummary[] | null;
  search: string;
  selected: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const filtered = useMemo(() => {
    if (!items) return null;
    const q = search.trim().toLowerCase();
    return q ? items.filter((s) => s.id.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)) : items;
  }, [items, search]);

  if (filtered === null) return <Loading />;
  if (filtered.length === 0) {
    return (
      <div className="px-2 py-3 text-xs text-zinc-500">
        No saved designs yet. Click <span className="font-mono text-zinc-400">Save</span> in the
        header to persist the current design here.
      </div>
    );
  }

  return (
    <ul className="space-y-1 text-sm">
      {filtered.map((s) => {
        const active = selected === s.id;
        return (
          <li key={s.id} className="flex items-stretch gap-1">
            <button
              onClick={() => onSelect(s.id)}
              className={`flex-1 rounded px-2 py-1.5 text-left transition-colors ${
                active
                  ? "bg-blue-500/15 text-blue-100 ring-1 ring-blue-400/40"
                  : "hover:bg-zinc-900"
              }`}
            >
              <div className="truncate font-medium">{s.name || s.id}</div>
              <div className="mt-0.5 truncate text-xs text-zinc-500">
                {s.chip_family} · {s.board_library_id} · {s.component_count} comp
              </div>
              <div className="mt-0.5 truncate text-[10px] text-zinc-600">
                saved {relativeTime(s.saved_at)}
              </div>
            </button>
            <button
              onClick={() => {
                if (confirm(`Delete saved design "${s.name || s.id}"?`)) onDelete(s.id);
              }}
              title={`Delete ${s.id}`}
              className="rounded border border-zinc-800 px-2 text-xs text-zinc-500 transition-colors hover:border-red-500/40 hover:bg-red-500/10 hover:text-red-300"
            >
              ✕
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function relativeTime(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const dSec = (Date.now() - t) / 1000;
  if (dSec < 60) return "just now";
  if (dSec < 3600) return `${Math.round(dSec / 60)}m ago`;
  if (dSec < 86400) return `${Math.round(dSec / 3600)}h ago`;
  return `${Math.round(dSec / 86400)}d ago`;
}

function ExamplesList({
  items, search, selected, onSelect,
}: {
  items: ExampleSummary[] | null;
  search: string;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const filtered = useMemo(() => {
    if (!items) return null;
    const q = search.trim().toLowerCase();
    return q ? items.filter((e) => e.id.toLowerCase().includes(q) || e.name.toLowerCase().includes(q)) : items;
  }, [items, search]);

  if (filtered === null) return <Loading />;
  if (filtered.length === 0) return <Empty>no examples</Empty>;

  return (
    <ul className="space-y-1 text-sm">
      {filtered.map((e) => {
        const active = selected === e.id;
        return (
          <li key={e.id}>
            <button
              onClick={() => onSelect(e.id)}
              className={`w-full rounded px-2 py-1.5 text-left transition-colors ${
                active
                  ? "bg-blue-500/15 text-blue-100 ring-1 ring-blue-400/40"
                  : "hover:bg-zinc-900"
              }`}
            >
              <div className="truncate font-medium">{e.name}</div>
              <div className="mt-0.5 truncate text-xs text-zinc-500">
                {e.chip_family} · {e.board_library_id}
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function BoardsList({
  items, search, onSelect,
}: {
  items: BoardSummary[] | null;
  search: string;
  onSelect: (id: string) => void;
}) {
  const filtered = useMemo(() => {
    if (!items) return null;
    const q = search.trim().toLowerCase();
    return q ? items.filter((b) => b.id.toLowerCase().includes(q) || b.name.toLowerCase().includes(q)) : items;
  }, [items, search]);

  if (filtered === null) return <Loading />;
  if (filtered.length === 0) return <Empty>no boards</Empty>;

  return (
    <ul className="space-y-1 text-sm">
      {filtered.map((b) => (
        <li key={b.id}>
          <button
            onClick={() => onSelect(b.id)}
            className="w-full rounded px-2 py-1.5 text-left transition-colors hover:bg-zinc-900"
          >
            <div className="truncate font-medium">{b.name}</div>
            <div className="mt-0.5 truncate text-xs text-zinc-500">
              {b.chip_variant} · {b.framework}
              {b.flash_size_mb ? ` · ${b.flash_size_mb}MB` : ""}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

function ComponentsList({
  items, search, onSelect,
}: {
  items: ComponentSummary[] | null;
  search: string;
  onSelect: (id: string) => void;
}) {
  const filtered = useMemo(() => {
    if (!items) return null;
    const q = search.trim().toLowerCase();
    return q
      ? items.filter((c) =>
          c.id.toLowerCase().includes(q)
          || c.name.toLowerCase().includes(q)
          || c.category.toLowerCase().includes(q)
          || c.use_cases.some((u) => u.toLowerCase().includes(q))
          || c.aliases.some((a) => a.toLowerCase().includes(q))
        )
      : items;
  }, [items, search]);

  if (filtered === null) return <Loading />;
  if (filtered.length === 0) return <Empty>no components</Empty>;

  return (
    <ul className="space-y-1 text-sm">
      {filtered.map((c) => (
        <li key={c.id}>
          <button
            onClick={() => onSelect(c.id)}
            className="w-full rounded px-2 py-1.5 text-left transition-colors hover:bg-zinc-900"
          >
            <div className="truncate font-medium">{c.name}</div>
            <div className="mt-0.5 truncate text-xs text-zinc-500">
              {c.category}
              {c.required_components.length ? ` · ${c.required_components.join(", ")}` : ""}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

function Loading() {
  return <div className="px-2 py-3 text-xs text-zinc-500">loading...</div>;
}
function Empty({ children }: { children: React.ReactNode }) {
  return <div className="px-2 py-3 text-xs text-zinc-500">{children}</div>;
}
